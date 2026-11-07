"""Claim amount measures: CL01 paid, CL02 case reserve, CL03 incurred, CL06 severity, CL10
paid-to-incurred, CL11 case reserve run-off, CL12 large-loss share, RC01 and RC02 recoveries.

Every function takes the spec, the inputs and the request and returns `Computed` or `Missing`;
the engine has checked the request against the spec before it is called.
"""

from collections.abc import Sequence
from datetime import date

import polars as pl

from actuarycanary.measures.claim_base import (
    CATASTROPHE,
    LARGE,
    NIL,
    amounts_at,
    flows,
    header,
    left_out,
    size_classes,
    with_dimensions,
)
from actuarycanary.measures.common import (
    add_period,
    group_agg,
    keep_columns,
    note_when,
    periods_between,
    ratio_columns,
    refs,
)
from actuarycanary.measures.model import (
    NOTE,
    REF,
    VALUE,
    Computed,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.periods import month_end, month_index

CONCEPT = "claim_valuations"
PROXY_NOTE = "origin is the month of the first valuation, a proxy (CV04)"


def group_keys(request: MeasureRequest) -> list[str]:
    """The breakdown columns; the ORIGINAL view never adds currencies, so it groups by them."""
    keys = list(request.breakdowns)
    if request.basis.currency is CurrencyView.ORIGINAL and "currency" not in keys:
        keys.append("currency")
    return keys


def monthly_ends(inputs: MeasureInputs) -> list[date]:
    """Every month end from the first valuation to the cut-off."""
    first = inputs.feeds[CONCEPT]["valuation_date"].min()
    assert isinstance(first, date)
    return [month_end(m) for m in range(month_index(first), month_index(inputs.cut_off) + 1)]


def calendar_ends(inputs: MeasureInputs, request: MeasureRequest) -> list[tuple[str, date]]:
    """(label, end) of every calendar period of the file; the last ends at the cut-off."""
    first = inputs.feeds[CONCEPT]["valuation_date"].min()
    assert isinstance(first, date)
    periods = periods_between(first, inputs.cut_off, request.period, inputs.fiscal_year_start_month)
    return [(label, min(end, inputs.cut_off)) for label, _, end in periods]


def origin_notes(inputs: MeasureInputs, request: MeasureRequest) -> list[str]:
    if "origin_period" not in request.breakdowns:
        return []
    head = header(inputs, request)
    if inputs.has("claims") and not head["origin_proxy"].any():
        return []
    count = int(head["origin_proxy"].sum())
    return [f"{PROXY_NOTE}: {count} claims"] if count else []


def prepared(
    states: pl.DataFrame, inputs: MeasureInputs, request: MeasureRequest
) -> tuple[pl.DataFrame, list[str]]:
    """States with the breakdown columns of `request` added (claim attributes, origin,
    class, status at the date, the valuation date asked for)."""
    states = states.rename({"valuation_date": "row_date"}).with_columns(
        pl.col("status").alias("claim_status"),
        *([pl.col("end").alias("valuation_date")] if "end" in states.columns else []),
    )
    return with_dimensions(states, request.breakdowns, inputs, request)


def _stock(
    inputs: MeasureInputs, request: MeasureRequest, measure: str, label: str
) -> Computed | Missing:
    keys = group_keys(request)
    ends = monthly_ends(inputs) if "valuation_date" in keys else [inputs.cut_off]
    states, notes = amounts_at(inputs, request.basis, measure, ends)
    states, left = left_out(states, label)
    states, dim_notes = prepared(states, inputs, request)
    if "valuation_date" in keys and len(ends) > 1 and len(inputs.rates.rates) > 1:
        notes.append(
            "amounts of every valuation date are converted at the constant rate of the cut-off, "
            "not at the period-end rate of that date (CV01, development view)"
        )
    frame = group_agg(states, keys, [pl.col(VALUE).sum(), refs(CONCEPT)])
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame,
        tuple([*notes, *left, *dim_notes, *origin_notes(inputs, request)]),
        (CONCEPT,),
    )


def flow_frame(
    inputs: MeasureInputs, request: MeasureRequest, measure: str, label: str
) -> tuple[pl.DataFrame, list[str]]:
    """Flows of `measure` with the breakdown columns and `calendar_period`."""
    rows, notes = flows(inputs, request.basis, measure)
    rows, left = left_out(rows, label)
    rows = rows.rename({"valuation_date": "row_date"}).with_columns(
        pl.col("status").alias("claim_status")
    )
    rows = add_period(
        rows, "row_date", "calendar_period", request.period, inputs.fiscal_year_start_month
    )
    rows, dim_notes = with_dimensions(rows, request.breakdowns, inputs, request)
    return rows, [*notes, *left, *dim_notes]


def paid(spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest) -> Computed | Missing:
    """CL01: cumulative paid at the cut-off or at each month end, or the paid flows by period."""
    if "calendar_period" in request.breakdowns:
        rows, notes = flow_frame(inputs, request, "paid", "paid flows")
        keys = group_keys(request)
        frame = group_agg(rows, keys, [pl.col(VALUE).sum(), refs(CONCEPT)])
        return Computed(keep_columns(frame, keys).sort(keys), tuple(notes), (CONCEPT,))
    return _stock(inputs, request, "paid", "paid")


def case_reserve(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL02: the case reserve at the cut-off or at each month end."""
    return _stock(inputs, request, "case_reserve", "case reserve")


def incurred(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL03: paid plus case reserve as of the date; by calendar period, its movement."""
    if "calendar_period" not in request.breakdowns:
        return _stock(inputs, request, "incurred", "incurred")
    keys = group_keys(request)
    stock_keys = [k for k in keys if k != "calendar_period"]
    ends = calendar_ends(inputs, request)
    states, notes = amounts_at(inputs, request.basis, "incurred", [e for _, e in ends])
    states, left = left_out(states, "incurred")
    states, dim_notes = prepared(states, inputs, request)
    states = add_period(
        states, "end", "calendar_period", request.period, inputs.fiscal_year_start_month
    )
    stock = group_agg(
        states, [*stock_keys, "calendar_period", "end"], [pl.col(VALUE).sum(), refs(CONCEPT)]
    )
    # every group has a stock at every period end, zero where it has no claim yet
    groups = (
        stock.select(stock_keys).unique(maintain_order=True)
        if stock_keys
        else pl.DataFrame({"_": [0]})
    )
    grid = groups.join(
        pl.DataFrame(
            {"calendar_period": [p for p, _ in ends], "end": [e for _, e in ends]},
            schema={"calendar_period": pl.String, "end": pl.Date},
        ),
        how="cross",
    )
    on = [*stock_keys, "calendar_period", "end"]
    full = grid.join(stock, on=on, how="left").with_columns(pl.col(VALUE).fill_null(0.0))
    moved = (
        full.sort([*stock_keys, "end"])
        .with_columns(
            (
                pl.col(VALUE) - pl.col(VALUE).shift(1).over(stock_keys).fill_null(0.0)
                if stock_keys
                else pl.col(VALUE) - pl.col(VALUE).shift(1).fill_null(0.0)
            ).alias(VALUE)
        )
        .drop("end", *(["_"] if not stock_keys else []))
    )
    return Computed(
        keep_columns(moved, keys),
        tuple([*notes, *left, *dim_notes]),
        (CONCEPT,),
    )


def severity(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL06: incurred of the claims of an origin and size class over their non-nil count."""
    exclude_nil = bool(request.param("exclude_nil", True))
    keys = group_keys(request)
    states, notes = amounts_at(inputs, request.basis, "incurred", [inputs.cut_off])
    states, left = left_out(states, "incurred")
    states, dim_notes = prepared(states, inputs, request)
    counted = (pl.col("status") != NIL) if exclude_nil else pl.lit(True)
    states = states.with_columns(counted.cast(pl.Int64).alias("_counted"))
    aggs = [
        pl.col(VALUE).sum().alias("numerator"),
        pl.col("_counted").sum().alias("denominator"),
        refs(CONCEPT),
    ]
    by_class = "claim_size_class" in keys
    plain_keys = [k for k in keys if k != "claim_size_class"]
    frame = group_agg(states, keys, aggs)
    if by_class:
        everything = group_agg(states, plain_keys, aggs).with_columns(
            pl.lit("all").alias("claim_size_class")
        )
        frame = pl.concat([frame, everything.select(frame.columns)])
    frame = frame.with_columns(
        *ratio_columns(),
        note_when(pl.col("denominator") <= 0, "no non-nil claims: not computed").alias(NOTE),
    )
    if inputs.has("claims") is False:
        notes.append("without claims, all claims form one segment and line UNKNOWN (CV04)")
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame,
        tuple([*notes, *left, *dim_notes, *origin_notes(inputs, request)]),
        (CONCEPT,),
    )


def large_loss_share(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL12: incurred of LARGE and CATASTROPHE claims over all incurred, by origin."""
    keys = group_keys(request)
    states, notes = amounts_at(inputs, request.basis, "incurred", [inputs.cut_off])
    states, left = left_out(states, "incurred")
    states, dim_notes = prepared(states, inputs, request)
    classes, _ = size_classes(inputs, request)
    states = states.drop("claim_size_class", strict=False).join(
        classes.select("claim_id", "claim_size_class", "threshold"), on="claim_id", how="left"
    )
    total = pl.col(VALUE).sum()
    frame = group_agg(
        states,
        keys,
        [
            pl.col(VALUE).filter(pl.col("claim_size_class") == LARGE).sum().alias("large"),
            pl.col(VALUE)
            .filter(pl.col("claim_size_class") == CATASTROPHE)
            .sum()
            .alias("catastrophe"),
            total.alias("denominator"),
            pl.col("threshold").is_null().all().alias("_no_large"),
            refs(CONCEPT),
        ],
    ).with_columns((pl.col("large") + pl.col("catastrophe")).alias("numerator"))
    frame = frame.with_columns(
        *ratio_columns(),
        pl.when(pl.col("denominator") > 0)
        .then(pl.col("large") / pl.col("denominator"))
        .alias("large_share"),
        pl.when(pl.col("denominator") > 0)
        .then(pl.col("catastrophe") / pl.col("denominator"))
        .alias("catastrophe_share"),
    )
    frame = frame.with_columns(
        pl.when(pl.col("_no_large")).then(None).otherwise(pl.col(VALUE)).alias(VALUE),
        pl.when(pl.col("denominator") <= 0)
        .then(pl.lit("total incurred is zero: not computed"))
        .when(pl.col("_no_large"))
        .then(
            pl.lit(
                "no LARGE class in this group (too few claims for the percentile, CV08): "
                "not computed"
            )
        )
        .otherwise(pl.lit(""))
        .alias(NOTE),
    ).drop("_no_large")
    extreme = (inputs.extreme_value_note,) if inputs.extreme_value_note else ()
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame,
        tuple([*notes, *left, *dim_notes, *origin_notes(inputs, request), *extreme]),
        (CONCEPT,),
    )


def recovery_ratio(
    inputs: MeasureInputs, request: MeasureRequest, recovery: str, column: str
) -> Computed | Missing:
    """RC01 and RC02: recovered to date, or its flow in a period, over paid."""
    keys = group_keys(request)
    if "calendar_period" in request.breakdowns:
        top, notes = flow_frame(inputs, request, recovery, recovery)
        bottom, _ = flow_frame(inputs, request, "paid", "paid flows")
    else:
        numerator_states, notes = amounts_at(inputs, request.basis, recovery, [inputs.cut_off])
        denominator_states, _ = amounts_at(inputs, request.basis, "paid", [inputs.cut_off])
        top, left_top = left_out(numerator_states, recovery)
        bottom, left_bottom = left_out(denominator_states, "paid")
        top, dim_notes = prepared(top, inputs, request)
        bottom, _ = prepared(bottom, inputs, request)
        notes = [*notes, *left_top, *left_bottom, *dim_notes]
    upper = group_agg(top, keys, [pl.col(VALUE).sum().alias("numerator"), refs(CONCEPT)])
    lower = group_agg(bottom, keys, [pl.col(VALUE).sum().alias("denominator")])
    frame = (
        upper.join(lower, on=keys, how="full", coalesce=True)
        if keys
        else pl.concat([upper, lower], how="horizontal")
    )
    frame = frame.with_columns(
        pl.col("numerator").fill_null(0.0),
        pl.col("denominator").fill_null(0.0),
    ).with_columns(
        *ratio_columns(),
        note_when(pl.col("denominator") <= 0, "paid is zero: not computed").alias(NOTE),
    )
    if "origin_period" in keys and "calendar_period" not in keys:
        notes.append(
            "recoveries arrive long after payment: ratios of recent origins are low by "
            "construction; compare origins at the same development age"
        )
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame,
        tuple([*notes, *origin_notes(inputs, request)]),
        (CONCEPT,),
    )


def subrogation_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    return recovery_ratio(inputs, request, "subrogation", "subrogation_to_date")


def salvage_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    return recovery_ratio(inputs, request, "salvage", "salvage_to_date")


def earlier_valuation(inputs: MeasureInputs, request: MeasureRequest) -> date:
    """The first valuation of a two-valuation measure: the setting or a year before the cut-off."""
    return request.earlier or month_end(month_index(inputs.cut_off) - 12)


def case_reserve_run_off(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL11: what the claims with a reserve at v0 paid since, plus their reserve at v1, over their
    reserve at v0."""
    v0, v1 = earlier_valuation(inputs, request), inputs.cut_off
    if v0 >= v1:
        return Missing(f"the earlier valuation {v0} is not before the cut-off {v1}")
    keys = group_keys(request)
    reserve, notes = amounts_at(inputs, request.basis, "case_reserve", [v0, v1])
    paid_states, _ = amounts_at(inputs, request.basis, "paid", [v0, v1])
    reserve, left = left_out(reserve, "case reserve")
    both = reserve.select(
        "claim_id",
        "end",
        "status",
        "currency",
        "valuation_date",
        pl.col(VALUE).alias("reserve"),
        REF,
    ).join(
        paid_states.select("claim_id", "end", pl.col(VALUE).alias("paid")),
        on=["claim_id", "end"],
        how="left",
    )
    first = both.filter(pl.col("end") == v0)
    last = both.filter(pl.col("end") == v1).select(
        "claim_id",
        pl.col("reserve").alias("reserve_end"),
        pl.col("paid").alias("paid_end"),
        pl.col("valuation_date").alias("last_row"),
        pl.col("status").alias("status_end"),
        pl.col(REF).alias("ref_end"),
    )
    cohort = first.filter(pl.col("reserve") > 0).join(last, on="claim_id", how="left")
    cohort = cohort.with_columns(
        pl.col("reserve_end").fill_null(0.0),
        pl.col("paid_end").fill_null(pl.col("paid")),
        (pl.col("last_row") <= v0).fill_null(True).alias("_dropped"),
    ).with_columns(
        (pl.col("paid_end") - pl.col("paid") + pl.col("reserve_end")).alias(VALUE),
        pl.col(REF).alias("ref_start"),
    )
    cohort = cohort.rename({"valuation_date": "row_date"}).with_columns(
        pl.col("status").alias("claim_status")
    )
    cohort, dim_notes = with_dimensions(cohort, request.breakdowns, inputs, request)
    frame = group_agg(
        cohort,
        keys,
        [
            pl.col(VALUE).sum().alias("numerator"),
            pl.col("reserve").sum().alias("denominator"),
            pl.col("claim_id").n_unique().alias("claims"),
            pl.col("_dropped").sum().alias("without_later_row"),
            pl.concat_list("ref_start", "ref_end")
            .list.explode()
            .unique()
            .sort()
            .alias(f"refs_{CONCEPT}"),
        ],
    ).with_columns(
        *ratio_columns(),
        (pl.col("denominator") - pl.col("numerator")).alias("run_off_result"),
        note_when(pl.col("denominator") <= 0, "cohort reserve is zero: not computed").alias(NOTE),
    )
    if frame.height == 0 and not keys:  # no claim has a reserve at v0
        frame = pl.DataFrame(
            {
                "numerator": [0.0],
                "denominator": [0.0],
                "claims": [0],
                "without_later_row": [0],
                "value": [None],
                "run_off_result": [0.0],
                "note": ["cohort reserve is zero: not computed"],
            },
            schema_overrides={"value": pl.Float64},
        )
    listed = cohort.filter(pl.col("_dropped")).select("claim_id", "row_date", "status")
    extra = (
        [
            f"{listed.height} claims have no row after {v0}: their last row is carried forward "
            "and they are listed"
        ]
        if listed.height
        else []
    )
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame,
        tuple(
            [
                f"cohort of claims with a reserve at {v0}, measured at {v1}",
                *notes,
                *left,
                *dim_notes,
                *extra,
            ]
        ),
        (CONCEPT,),
        {"carried_forward": listed} if listed.height else {},
    )


def _triangle_cells(inputs: MeasureInputs, request: MeasureRequest) -> pl.DataFrame | Missing:
    triangles = inputs.triangles
    if triangles is None:
        return Missing("no triangles were built (MT01)")
    settings = triangles.settings
    if (
        settings.reinsurance_basis is not request.basis.reinsurance
        or settings.value_basis is not request.basis.value
    ):
        return Missing(
            f"the triangles are built on {settings.reinsurance_basis.value}, "
            f"{settings.value_basis.value}, not on {request.basis.reinsurance.value}, "
            f"{request.basis.value.value}"
        )
    rows: list[dict[str, object]] = []
    for group in triangles.groups:
        paid_t, incurred_t = triangles.get("paid", group), triangles.get("incurred", group)
        for i, origin in enumerate(paid_t.origins):
            for j, age in enumerate(paid_t.ages):
                if not paid_t.observed[i, j]:
                    continue
                rows.append(
                    {
                        "segment": group[0],
                        "line": group[1],
                        "origin_period": origin,
                        "development_period": f"{age}",
                        "age": age,
                        "paid": float(paid_t.cumulative[i, j]),
                        "incurred": float(incurred_t.cumulative[i, j]),
                        "latest": bool(j == paid_t.latest_index[i]),
                    }
                )
    return pl.DataFrame(rows)


def paid_to_incurred(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """CL10: the cumulative paid triangle over the cumulative incurred triangle, cell by cell."""
    cells = _triangle_cells(inputs, request)
    if isinstance(cells, Missing):
        return cells
    keys = list(request.breakdowns)
    frame = group_agg(
        cells,
        keys,
        [pl.col("paid").sum().alias("numerator"), pl.col("incurred").sum().alias("denominator")],
    ).with_columns(*ratio_columns())
    frame = frame.with_columns(
        pl.when(pl.col("denominator") == 0)
        .then(pl.lit("incurred is zero: not computed"))
        .when(pl.col(VALUE) > 1)
        .then(pl.lit("above 1: negative case reserves"))
        .otherwise(pl.lit(""))
        .alias(NOTE)
    )
    notes = ["lineage: the cells of the paid and incurred triangles (MT01) of the valuation rows"]
    # a column whose ratio on the latest diagonal lies outside the earlier ratios of the column
    if {"origin_period", "development_period"} <= set(keys):
        notes += _diagonal_notes(cells, keys)
    return Computed(
        keep_columns(frame, keys).sort(keys) if keys else frame, tuple(notes), (CONCEPT,)
    )


def _diagonal_notes(cells: pl.DataFrame, keys: Sequence[str]) -> list[str]:
    by = [k for k in ("segment", "line") if k in keys]
    notes: list[str] = []
    ratio = cells.filter(pl.col("incurred") > 0).with_columns(
        (pl.col("paid") / pl.col("incurred")).alias("r")
    )
    for key, part in ratio.group_by([*by, "age"] if by else ["age"], maintain_order=True):
        earlier = part.filter(~pl.col("latest"))["r"]
        latest = part.filter(pl.col("latest"))["r"]
        if earlier.len() >= 2 and latest.len() >= 1:
            value = latest.item(0)
            if value < earlier.min() or value > earlier.max():  # type: ignore[operator]
                where = " / ".join(str(k) for k in (key if isinstance(key, tuple) else (key,)))
                notes.append(
                    f"{where}: the latest diagonal ratio lies outside the earlier ratios of its "
                    "column: possible change in case reserving or payment speed"
                )
    return notes
