"""Claim count and time measures: CL04 counts by status, CL05 frequency, CL07 reporting delay,
CL08 settlement time and CL09 settlement rate (blueprint 8.1, decision 0051)."""

from datetime import date

import numpy as np
import polars as pl

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.measures.claim_amounts import (
    CONCEPT,
    calendar_ends,
    monthly_ends,
    origin_notes,
)
from actuarycanary.measures.claim_base import (
    HEADER_DIMS,
    NIL,
    asof_states,
    status_rows,
    with_dimensions,
)
from actuarycanary.measures.common import (
    add_period,
    group_agg,
    keep_columns,
    ratio_columns,
    refs,
    span_labels,
)
from actuarycanary.measures.model import (
    NOTE,
    REF,
    VALUE,
    Computed,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.premium import PremiumSettings, earned_exposure

OPEN = ("OPEN", "REOPENED", "LITIGATED")
CLOSED = ("CLOSED", "CLOSED_NIL")
STOCK_TYPES = ("reported", "open", "closed", "nil_closed", "reopened", "litigated", "UNMAPPED")
FLOW_TYPES = ("newly_reported", "closed", "reopened")
MIN_FOR_PERCENTILES = 5  # CL07
DELAY_PERCENTILES = (0.5, 0.75, 0.9, 0.95)
SETTLEMENT_PERCENTILES = (0.5, 0.75, 0.9)


def _indicators() -> list[pl.Expr]:
    status = pl.col("status")
    return [
        pl.lit(1).alias("reported"),
        status.is_in(OPEN).cast(pl.Int64).alias("open"),
        status.is_in(CLOSED).cast(pl.Int64).alias("closed"),
        (status == NIL).cast(pl.Int64).alias("nil_closed"),
        (status == "REOPENED").cast(pl.Int64).alias("reopened"),
        (status == "LITIGATED").cast(pl.Int64).alias("litigated"),
        (status == "UNMAPPED").cast(pl.Int64).alias("UNMAPPED"),
    ]


def _with_status_dims(
    states: pl.DataFrame, inputs: MeasureInputs, request: MeasureRequest
) -> tuple[pl.DataFrame, list[str]]:
    states = states.rename({"valuation_date": "row_date"}).with_columns(
        pl.col("status").alias("claim_status"),
        *([pl.col("end").alias("valuation_date")] if "end" in states.columns else []),
    )
    return with_dimensions(states, request.breakdowns, inputs, request)


def _stock_counts(inputs: MeasureInputs, request: MeasureRequest) -> Computed:
    keys = list(request.breakdowns)
    ends = monthly_ends(inputs) if "valuation_date" in keys else [inputs.cut_off]
    states = asof_states(status_rows(inputs), ends)
    states, notes = _with_status_dims(states, inputs, request)
    states = states.with_columns(_indicators())
    frame = group_agg(states, keys, [*[pl.col(t).sum() for t in STOCK_TYPES], refs(CONCEPT)])
    long = frame.unpivot(
        on=list(STOCK_TYPES),
        index=[*keys, f"refs_{CONCEPT}"],
        variable_name="count_type",
        value_name=VALUE,
    ).with_columns(pl.col(VALUE).cast(pl.Float64))
    return Computed(
        keep_columns(long, [*keys, "count_type"]).sort([*keys, "count_type"]),
        tuple([*notes, *origin_notes(inputs, request)]),
        (CONCEPT,),
    )


def _flow_events(inputs: MeasureInputs, request: MeasureRequest) -> pl.DataFrame:
    """One row per valuation row with the events it books: newly reported (a claim's first row),
    closed (a transition into a closed status) and reopened (closed to open), CV04."""
    rows = (
        inputs.feeds[CONCEPT]
        .filter(pl.col("valuation_date") <= inputs.cut_off)
        .sort("claim_id", "valuation_date", SOURCE_ROW)
        .select("claim_id", "valuation_date", "status", REF)
    )
    previous = pl.col("status").shift(1).over("claim_id")
    return rows.with_columns(
        previous.is_null().cast(pl.Int64).alias("newly_reported"),
        (pl.col("status").is_in(CLOSED) & ~previous.fill_null("").is_in(CLOSED))
        .cast(pl.Int64)
        .alias("closed"),
        (previous.is_in(CLOSED) & pl.col("status").is_in(OPEN)).cast(pl.Int64).alias("reopened"),
    )


def _flow_counts(inputs: MeasureInputs, request: MeasureRequest) -> Computed:
    keys = list(request.breakdowns)
    events = _flow_events(inputs, request).rename({"valuation_date": "row_date"})
    events = events.with_columns(pl.col("status").alias("claim_status"))
    events = add_period(
        events, "row_date", "calendar_period", request.period, inputs.fiscal_year_start_month
    )
    events, notes = with_dimensions(events, request.breakdowns, inputs, request)
    frame = group_agg(events, keys, [*[pl.col(t).sum() for t in FLOW_TYPES], refs(CONCEPT)])
    long = frame.unpivot(
        on=list(FLOW_TYPES),
        index=[*keys, f"refs_{CONCEPT}"],
        variable_name="count_type",
        value_name=VALUE,
    ).with_columns(pl.col(VALUE).cast(pl.Float64))
    return Computed(
        keep_columns(long, [*keys, "count_type"]).sort([*keys, "count_type"]),
        tuple([*notes, *origin_notes(inputs, request)]),
        (CONCEPT,),
    )


def claim_counts(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL04: stock counts at the cut-off (or month ends), flow counts by calendar period."""
    if "calendar_period" in request.breakdowns:
        return _flow_counts(inputs, request)
    return _stock_counts(inputs, request)


def settlement_rate(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL09: closings in a period over the claims open at its start plus those newly reported."""
    keys = list(request.breakdowns)
    stock_keys = [k for k in keys if k != "calendar_period"]
    periods = calendar_ends(inputs, request)
    first_day = inputs.feeds[CONCEPT]["valuation_date"].min()
    assert isinstance(first_day, date)
    # the open count at the start of a period is the open stock at the end of the one before
    previous = {label: (periods[i - 1][1] if i else None) for i, (label, _) in enumerate(periods)}
    ends = [e for e in previous.values() if e is not None]
    opened = pl.DataFrame(
        schema={
            **{k: pl.String for k in stock_keys},
            "calendar_period": pl.String,
            "open": pl.Int64,
        }
    )
    if ends:
        states = asof_states(status_rows(inputs), ends)
        states, _ = _with_status_dims(states, inputs, request)
        states = states.with_columns(pl.col("status").is_in(OPEN).cast(pl.Int64).alias("open"))
        stock = group_agg(states, [*stock_keys, "end"], [pl.col("open").sum(), refs(CONCEPT)])
        by_end = {e: label for label, e in previous.items() if e is not None}
        stock = stock.with_columns(
            pl.col("end").replace_strict(by_end, return_dtype=pl.String).alias("calendar_period")
        ).drop("end")
        opened = stock.select(*stock_keys, "calendar_period", "open")
    events = _flow_events(inputs, request).rename({"valuation_date": "row_date"})
    events = events.with_columns(pl.col("status").alias("claim_status"))
    events = add_period(
        events, "row_date", "calendar_period", request.period, inputs.fiscal_year_start_month
    )
    events, notes = with_dimensions(events, request.breakdowns, inputs, request)
    movement = group_agg(
        events,
        keys,
        [pl.col("closed").sum(), pl.col("newly_reported").sum(), refs(CONCEPT)],
    )
    frame = movement.join(opened, on=[*stock_keys, "calendar_period"], how="left")
    first_period = periods[0][0]
    frame = frame.with_columns(
        pl.col("open").fill_null(0),
        (pl.col("open").fill_null(0) + pl.col("newly_reported")).alias("denominator"),
        pl.col("closed").alias("numerator"),
    ).with_columns(
        *ratio_columns(),
        pl.when(pl.col("calendar_period") == first_period)
        .then(pl.lit("first period of the file: the open count at its start is unknown"))
        .when(pl.col("denominator") <= 0)
        .then(pl.lit("no open or new claims: not computed"))
        .when(pl.col("numerator") > pl.col("denominator"))
        .then(pl.lit("above 1: claims reopened and closed again within the period"))
        .otherwise(pl.lit(""))
        .alias(NOTE),
    )
    frame = frame.with_columns(
        pl.when(pl.col("calendar_period") == first_period)
        .then(None)
        .otherwise(pl.col(VALUE))
        .alias(VALUE)
    ).drop("open", "closed", "newly_reported")
    return Computed(
        keep_columns(frame, keys).sort(keys),
        tuple([*notes, *origin_notes(inputs, request)]),
        (CONCEPT,),
    )


def frequency(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL05: reported claims of an accident period over the earned exposure of the same period,
    segment and line."""
    if "channel" in request.breakdowns:
        return Missing("claims carry no channel, so claims cannot be split by channel")
    exclude_nil = bool(request.param("exclude_nil", True))
    keys = list(request.breakdowns)
    by = [k for k in keys if k in HEADER_DIMS and k not in ("cause",)]
    claims = inputs.feeds["claims"]
    rows = claims.filter(
        pl.col("occurrence_date").is_not_null() & (pl.col("report_date") <= inputs.cut_off)
    )
    without_date = claims.filter(pl.col("occurrence_date").is_null()).height
    status = asof_states(status_rows(inputs), [inputs.cut_off]).select(
        "claim_id", "status", pl.col(REF).alias("valuation_ref")
    )
    rows = rows.join(status, on="claim_id", how="left")
    if exclude_nil:
        rows = rows.filter(pl.col("status").fill_null("") != NIL)
    rows = add_period(
        rows, "occurrence_date", "origin_period", request.period, inputs.fiscal_year_start_month
    )
    attributes = [pl.col(k).fill_null("UNKNOWN") for k in by if k in rows.columns]
    rows = rows.with_columns(
        *attributes, *[pl.lit("UNKNOWN").alias(k) for k in by if k not in rows.columns]
    )
    numerator = group_agg(
        rows,
        [*by, "origin_period"],
        [pl.len().alias("numerator"), refs("claims", REF)],
    )
    settings = PremiumSettings(
        period=request.period,
        fiscal_year_start_month=inputs.fiscal_year_start_month,
        cut_off=inputs.cut_off,
    )
    exposure = earned_exposure(
        inputs.feeds["policies"], settings, inputs.cut_off, by=by, row_column=REF
    )
    denominator = (
        exposure.rename({"period": "origin_period"})
        .drop("period_number")
        .cast({"origin_period": pl.String})
    )
    keep = [*by, "origin_period"]
    # accident periods outside the dates the claims cover have no claims data: missing, not zero
    covered = span_labels(
        claims["occurrence_date"].min(),
        claims["occurrence_date"].max(),
        request.period,
        inputs.fiscal_year_start_month,
    )
    denominator = denominator.filter(pl.col("origin_period").is_in(covered))
    both = numerator.join(denominator, on=keep, how="full", coalesce=True).with_columns(
        pl.col("numerator").fill_null(0),
        pl.col("earned_exposure").fill_null(0.0).alias("denominator"),
    )
    if "origin_period" not in keys:
        sums = [
            pl.col("numerator").sum(),
            pl.col("denominator").sum(),
            pl.col("refs_claims").explode().unique().sort().implode(),
            pl.col("policy_rows").explode().unique().sort().implode(),
        ]
        both = group_agg(both, by, sums)
    frame = both.with_columns(
        *ratio_columns(),
        pl.when(pl.col("denominator") <= 0)
        .then(pl.lit("earned exposure is zero: not computed"))
        .otherwise(pl.lit("reported frequency"))
        .alias(NOTE),
    ).rename({"policy_rows": "refs_policies"})
    notes = [
        "reported frequency: recent accident periods are understated because claims not yet "
        "reported are missing; see the reporting delay (CL07)"
    ]
    if without_date:
        notes.append(f"{without_date} claims without occurrence date excluded (DV-CLM-03)")
    return Computed(
        keep_columns(frame, keys).sort([k for k in keys if k in frame.columns]),
        tuple(notes),
        ("claims", "policies"),
    )


def _quantiles(values: pl.Series, ps: tuple[float, ...]) -> list[float | None]:
    if values.len() == 0:
        return [None] * len(ps)
    return [float(np.quantile(values.to_numpy(), p, method="linear")) for p in ps]


def reporting_delay(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL07: days from occurrence to report of claims reported by the cut-off, with the mean
    as the value and the percentiles beside it."""
    keys = list(request.breakdowns)
    claims = inputs.feeds["claims"]
    rows = claims.filter(
        pl.col("occurrence_date").is_not_null()
        & pl.col("report_date").is_not_null()
        & (pl.col("report_date") <= inputs.cut_off)
    ).with_columns(
        (pl.col("report_date") - pl.col("occurrence_date")).dt.total_days().alias("delay")
    )
    negative = rows.filter(pl.col("delay") < 0)
    rows = rows.filter(pl.col("delay") >= 0)
    rows = add_period(
        rows, "occurrence_date", "origin_period", request.period, inputs.fiscal_year_start_month
    ).with_columns(pl.col(REF).alias("claims_ref"))
    rows, notes = with_dimensions(rows, request.breakdowns, inputs, request)
    for name in HEADER_DIMS:
        if name in rows.columns:
            rows = rows.with_columns(pl.col(name).fill_null("UNKNOWN"))
    parts = rows.partition_by(keys, as_dict=True) if keys else {(): rows}
    out: list[dict[str, object]] = []
    for key, part in parts.items():
        delays = part["delay"]
        n = part.height
        row: dict[str, object] = dict(zip(keys, key, strict=True))
        row["n"] = n
        row[VALUE] = float(delays.mean()) if n else None  # type: ignore[arg-type]
        for p in DELAY_PERCENTILES:
            row[f"p{int(p * 100)}"] = None
        shown = _quantiles(delays, DELAY_PERCENTILES) if n >= MIN_FOR_PERCENTILES else None
        median = _quantiles(delays, (0.5,))[0]
        row["p50"] = median
        if shown is not None:
            for p, q in zip(DELAY_PERCENTILES, shown, strict=True):
                row[f"p{int(p * 100)}"] = q
        row["refs_claims"] = part["claims_ref"].unique().sort().to_list()
        out.append(row)
    schema = {k: pl.String for k in keys}
    frame = (
        pl.DataFrame(out, schema_overrides=schema, infer_schema_length=None)
        if out
        else pl.DataFrame()
    )
    if frame.height:
        frame = frame.with_columns(
            pl.when(pl.col("n") < MIN_FOR_PERCENTILES)
            .then(pl.lit("fewer than 5 claims: percentiles other than the median not shown"))
            .otherwise(pl.lit(""))
            .alias(NOTE)
        )
        frame = _incomplete(frame, rows, keys, inputs, request)
    extra = []
    if negative.height:
        extra.append(f"{negative.height} claims reported before they occurred excluded (DV-CLM-04)")
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys and frame.height else frame,
        tuple([*notes, *extra]),
        ("claims",),
    )


def _incomplete(
    frame: pl.DataFrame,
    rows: pl.DataFrame,
    keys: list[str],
    inputs: MeasureInputs,
    request: MeasureRequest,
) -> pl.DataFrame:
    """Mark origin periods younger than the 95th percentile delay of the mature periods."""
    if "origin_period" not in keys or rows.height == 0:
        return frame
    ends = (
        rows.group_by("origin_period")
        .agg(pl.col("occurrence_date").max().alias("last"))
        .with_columns(pl.col("last").dt.month_end())
    )
    p95_all = _quantiles(rows["delay"], (0.95,))[0] or 0.0
    mature_labels = ends.filter(pl.col("last") + pl.duration(days=int(p95_all)) <= inputs.cut_off)[
        "origin_period"
    ]
    mature = rows.filter(pl.col("origin_period").is_in(mature_labels.implode()))
    p95 = _quantiles(mature["delay"] if mature.height else rows["delay"], (0.95,))[0] or 0.0
    period_end = ends.with_columns(
        (pl.col("last") + pl.duration(days=int(p95)) > inputs.cut_off).alias("incomplete")
    ).select("origin_period", "incomplete")
    joined = frame.join(period_end, on="origin_period", how="left").with_columns(
        pl.col("incomplete").fill_null(False)
    )
    return joined.with_columns(
        pl.concat_str(
            pl.col(NOTE),
            pl.when(pl.col("incomplete") & (pl.col(NOTE) != ""))
            .then(pl.lit("; incomplete: long delays not yet observed"))
            .when(pl.col("incomplete"))
            .then(pl.lit("incomplete: long delays not yet observed"))
            .otherwise(pl.lit("")),
        ).alias(NOTE)
    )


def _close_dates(inputs: MeasureInputs) -> pl.DataFrame:
    """Per claim: the valuation date of the last transition into a closed status (derived)."""
    rows = (
        inputs.feeds[CONCEPT]
        .filter(pl.col("valuation_date") <= inputs.cut_off)
        .sort("claim_id", "valuation_date", SOURCE_ROW)
        .select("claim_id", "valuation_date", "status", REF)
    )
    previous = pl.col("status").shift(1).over("claim_id").fill_null("")
    closing = rows.filter(pl.col("status").is_in(CLOSED) & ~previous.is_in(CLOSED))
    return closing.group_by("claim_id", maintain_order=True).agg(
        pl.col("valuation_date").last().alias("derived_close"),
        pl.col(REF).last().alias("close_ref"),
    )


def settlement_time(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL08: days from report to close of the closed claims (mean as the value), with the
    product-limit survival curve (open claims censored) and its quantiles."""
    keys = list(request.breakdowns)
    claims = inputs.feeds["claims"].filter(
        pl.col("report_date").is_not_null() & (pl.col("report_date") <= inputs.cut_off)
    )
    status = asof_states(status_rows(inputs), [inputs.cut_off]).select(
        "claim_id", "status", pl.col(REF).alias("valuation_ref")
    )
    derived = _close_dates(inputs)
    data = claims.join(status, on="claim_id", how="inner").join(derived, on="claim_id", how="left")
    given = pl.col("close_date") if "close_date" in data.columns else pl.lit(None, pl.Date)
    closed = pl.col("status").is_in(CLOSED)
    data = data.with_columns(
        closed.alias("closed"),
        pl.coalesce(given, pl.col("derived_close")).alias("end_date"),
        (given.is_null() & closed).alias("is_derived"),
    )
    data = data.with_columns(
        pl.when(pl.col("closed"))
        .then((pl.col("end_date") - pl.col("report_date")).dt.total_days())
        .otherwise((pl.lit(inputs.cut_off) - pl.col("report_date")).dt.total_days())
        .alias("duration")
    )
    before = data.filter(pl.col("closed") & (pl.col("duration") < 0))
    data = data.filter(~pl.col("closed") | pl.col("duration").is_not_null()).filter(
        ~(pl.col("closed") & (pl.col("duration") < 0))
    )
    data = add_period(
        data, "report_date", "origin_period", request.period, inputs.fiscal_year_start_month
    ).with_columns(pl.col(REF).alias("claims_ref"))
    data, notes = with_dimensions(data, request.breakdowns, inputs, request)
    parts = data.partition_by(keys, as_dict=True) if keys else {(): data}
    summary: list[dict[str, object]] = []
    curves: list[pl.DataFrame] = []
    for key, part in parts.items():
        label = dict(zip(keys, key, strict=True))
        times, at_risk, events, survival = _product_limit(part)
        done = part.filter(pl.col("closed"))
        row: dict[str, object] = {
            **label,
            "closed": done.height,
            "open": part.height - done.height,
            VALUE: float(done["duration"].mean()) if done.height else None,  # type: ignore[arg-type]
            "derived_close_dates": int(done["is_derived"].sum()),
            "refs_claims": part["claims_ref"].unique().sort().to_list(),
        }
        beyond = []
        for p in SETTLEMENT_PERCENTILES:
            hit = [t for t, s in zip(times, survival, strict=True) if s <= 1 - p]
            row[f"p{int(p * 100)}"] = float(hit[0]) if hit else None
            if not hit:
                beyond.append(f"p{int(p * 100)}")
        row[NOTE] = ("beyond observed range: " + ", ".join(beyond)) if beyond else ""
        summary.append(row)
        curves.append(
            pl.DataFrame(
                {
                    **{k: [v] * len(times) for k, v in label.items()},
                    "duration_days": times,
                    "at_risk": at_risk,
                    "closed": events,
                    "survival": survival,
                },
                schema_overrides={k: pl.String for k in keys},
            )
        )
    schema = {k: pl.String for k in keys}
    frame = pl.DataFrame(summary, schema_overrides=schema, infer_schema_length=None)
    extra = []
    if before.height:
        extra.append(
            f"{before.height} claims closed before they were reported excluded (DV-CLM-05)"
        )
    derived_count = int(data.filter(pl.col("is_derived"))["claim_id"].len())
    if derived_count:
        extra.append(
            f"{derived_count} close dates derived from the last transition into a closed status "
            "(precision one month)"
        )
    survival_table = pl.concat(curves) if curves else pl.DataFrame()
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame,
        tuple([*notes, *extra, "open claims are censored at the cut-off"]),
        ("claims",),
        {"survival": survival_table},
    )


def _product_limit(part: pl.DataFrame) -> tuple[list[int], list[int], list[int], list[float]]:
    """Durations of the closings, claims at risk just before, closings, survival (Kaplan–Meier)."""
    durations = part["duration"].to_numpy()
    closed = part["closed"].to_numpy()
    times = sorted({int(t) for t in durations[closed]})
    at_risk, events, survival = [], [], []
    s = 1.0
    for t in times:
        n = int((durations >= t).sum())
        d = int(((durations == t) & closed).sum())
        s *= 1 - d / n
        at_risk.append(n)
        events.append(d)
        survival.append(s)
    return times, at_risk, events, survival
