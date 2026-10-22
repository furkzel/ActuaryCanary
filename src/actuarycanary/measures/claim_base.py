"""Claim states and flows on a basis, claim attributes and size classes: what the claim
measures stand on (CV01 to CV04, CV08).

A claim's state at a date is its latest valuation row on or before it (carry-forward). Amounts
are converted and restated by `convert.bases`, the same code the triangles use, so a measure at
the cut-off equals the latest diagonal of the matching triangle.
"""

from collections.abc import Sequence
from datetime import date

import polars as pl

from actuarycanary.convert import bases
from actuarycanary.convert.bases import RESTATED, ReinsuranceBasis, RowBasis, ValueBasis
from actuarycanary.convert.currency import Rule, lookup_rates
from actuarycanary.convert.market import ConversionError
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.measures.common import UNKNOWN, add_period
from actuarycanary.measures.model import REF, Basis, CurrencyView, MeasureInputs, MeasureRequest
from actuarycanary.structures.periods import month_end

HEADER_DIMS = ("segment", "line", "entity", "product", "partner", "cause")
ATTRIBUTES = (*HEADER_DIMS, "event_code", "occurrence_date", "report_date", "close_date")
ATTRITIONAL, LARGE, CATASTROPHE = "ATTRITIONAL", "LARGE", "CATASTROPHE"
NIL = "CLOSED_NIL"
STATES = ("claim_id", "valuation_date", "status", "currency", "value", "usable", REF)


def restated_rows(
    inputs: MeasureInputs, basis: Basis, names: Sequence[str]
) -> tuple[pl.DataFrame, list[str]]:
    """Valuation rows up to the cut-off with `r_<field>` columns on the currency and value basis,
    and the notes of the conversion (CV01, CV02)."""
    key = ("rows", basis.currency, basis.value, tuple(names))
    if key in inputs.cache:
        return inputs.cache[key]
    rows = inputs.feeds["claim_valuations"].filter(pl.col("valuation_date") <= inputs.cut_off)
    rows = rows.with_columns(
        [pl.col(n).fill_null(0.0) for n in bases.CEDED_COMPONENTS if n in rows.columns]
    )
    if basis.currency is CurrencyView.ORIGINAL:
        if basis.value is ValueBasis.INFLATION_ADJUSTED:
            raise bases.BasisUnavailableError(
                "inflation adjustment needs the reporting currency view: the index belongs to "
                "the reporting currency (CV02)"
            )
        result = rows.with_columns(
            *[pl.col(n).alias(RESTATED + n) for n in names],
            pl.lit(True).alias("ok_flow"),
            pl.lit(True).alias("ok_stock"),
        )
        notes: list[str] = []
    else:
        row_basis = RowBasis(
            inputs.reporting_currency,
            basis.value,
            inputs.rates,
            inputs.market,
            inputs.price_index,
            inputs.value_date or inputs.cut_off,
        )
        result, findings = bases.restate_rows(rows, names, row_basis)
        notes = sorted({f"{f.rule}: {f.message}" for f in findings if f.severity != "INFO"})
    inputs.cache[key] = (result, notes)
    return result, notes


def _columns(measure: str, basis: Basis, inputs: MeasureInputs) -> bases.MeasureColumns:
    present = list(inputs.feeds["claim_valuations"].columns)
    bases.required_columns([measure], basis.reinsurance, present)
    return bases.measure_columns(measure, basis.reinsurance)


def _names(measure: str, reinsurance: ReinsuranceBasis) -> list[str]:
    return list(dict.fromkeys(n for _, n in bases.components(measure, reinsurance)))


def amounts_at(
    inputs: MeasureInputs, basis: Basis, measure: str, ends: Sequence[date]
) -> tuple[pl.DataFrame, list[str]]:
    """One row per claim and date in `ends` that has a state then: `value` of `measure` in its
    latest row on or before the date (rows with an empty amount are left out of the measure,
    DV-CLV-02), `usable` False where no rate or index applied, the row used as `_ref`."""
    columns = _columns(measure, basis, inputs)
    rows, notes = restated_rows(inputs, basis, _names(measure, basis.reinsurance))
    chosen = (
        rows.filter(columns.present)
        .sort("claim_id", "valuation_date", SOURCE_ROW)
        .unique(subset=["claim_id", "valuation_date"], keep="last", maintain_order=True)
        .select(
            "claim_id",
            "valuation_date",
            "status",
            "currency",
            columns.value.alias("value"),
            columns.usable.alias("usable"),
            REF,
        )
        .sort("valuation_date")
    )
    return asof_states(chosen, ends), notes


def asof_states(chosen: pl.DataFrame, ends: Sequence[date]) -> pl.DataFrame:
    """The latest row of each claim on or before each date of `ends` (carry-forward, CV04).
    `chosen` has claim_id and valuation_date, one row per pair, sorted by valuation_date;
    claims with no row on or before a date have no state then."""
    grid = (
        chosen.select("claim_id")
        .unique(maintain_order=True)
        .join(pl.DataFrame({"end": list(ends)}, schema={"end": pl.Date}), how="cross")
        .sort("end")
    )
    return grid.join_asof(
        chosen,
        left_on="end",
        right_on="valuation_date",
        by="claim_id",
        strategy="backward",
        check_sortedness=False,
    ).filter(pl.col("valuation_date").is_not_null())


def status_rows(inputs: MeasureInputs) -> pl.DataFrame:
    """One row per claim and valuation date up to the cut-off: status and source row, sorted
    by date (the last of equal dates by source row wins)."""
    key = ("status_rows",)
    if key not in inputs.cache:
        inputs.cache[key] = (
            inputs.feeds["claim_valuations"]
            .filter(pl.col("valuation_date") <= inputs.cut_off)
            .sort("claim_id", "valuation_date", SOURCE_ROW)
            .unique(subset=["claim_id", "valuation_date"], keep="last", maintain_order=True)
            .select("claim_id", "valuation_date", "status", REF)
            .sort("valuation_date")
        )
    return inputs.cache[key]


def left_out(states: pl.DataFrame, what: str = "amount") -> tuple[pl.DataFrame, list[str]]:
    """The states that could be converted, and a note on the rest (CV01: reported apart)."""
    bad = states.filter(~pl.col("usable"))
    if bad.height == 0:
        return states, []
    claims = bad["claim_id"].n_unique()
    currencies = ", ".join(sorted(bad["currency"].drop_nulls().unique().to_list()))
    note = (
        f"{claims} claims in {currencies or 'unknown currency'} left out: no exchange rate or "
        f"index value applies to their {what} (CV01, CV02)"
    )
    return states.filter(pl.col("usable")), [note]


def flows(inputs: MeasureInputs, basis: Basis, measure: str) -> tuple[pl.DataFrame, list[str]]:
    """The flows of a cumulative amount (CV04): the difference of consecutive valuation rows
    of a claim, the first row in full, booked on the date of the later row.

    Nominal flows are converted at the average rate of their month (CV01); adjusted flows are
    restated by `convert.bases` and their differences taken. Columns: claim_id,
    valuation_date, status, currency, value (the flow), usable, _ref.
    """
    columns = _columns(measure, basis, inputs)
    names = _names(measure, basis.reinsurance)
    if any(n in bases.STOCK_COMPONENTS for n in names):
        raise bases.BasisUnavailableError(f"{measure} is a stock; it has no flows (CV04)")
    rows, notes = restated_rows(inputs, basis, names)
    raw = pl.sum_horizontal(
        sign * pl.col(name) for sign, name in bases.components(measure, basis.reinsurance)
    )
    chosen = (
        rows.filter(columns.present)
        .sort("claim_id", "valuation_date", SOURCE_ROW)
        .unique(subset=["claim_id", "valuation_date"], keep="last", maintain_order=True)
        .with_columns(raw.alias("_raw"), columns.value.alias("_restated"))
    )
    nominal = basis.value is ValueBasis.NOMINAL
    cumulative = pl.col("_raw" if nominal else "_restated")
    flow = chosen.with_columns(
        cumulative.diff().over("claim_id").fill_null(cumulative).alias("_flow")
    )
    if nominal and basis.currency is CurrencyView.REPORTING:
        keys = flow.select("currency", pl.col("valuation_date").alias("day"))
        rates = lookup_rates(inputs.market, inputs.reporting_currency, keys, Rule.DERIVED_FLOW)
        flow = flow.join(
            rates.select("currency", pl.col("day").alias("valuation_date"), "rate"),
            on=["currency", "valuation_date"],
            how="left",
        ).with_columns(
            (pl.col("_flow") * pl.col("rate")).alias("value"),
            pl.col("rate").is_not_null().alias("usable"),
        )
    else:
        flow = flow.with_columns(pl.col("_flow").alias("value"), columns.usable.alias("usable"))
    return flow.select(*STATES), notes


def first_rows(inputs: MeasureInputs) -> pl.DataFrame:
    """claim_id, first valuation date and its `_ref`, from rows up to the cut-off."""
    key = ("first",)
    if key not in inputs.cache:
        inputs.cache[key] = (
            inputs.feeds["claim_valuations"]
            .filter(pl.col("valuation_date") <= inputs.cut_off)
            .sort("claim_id", "valuation_date", SOURCE_ROW)
            .group_by("claim_id", maintain_order=True)
            .agg(
                pl.col("valuation_date").first().alias("first_valuation"),
                pl.col(REF).first().alias("first_ref"),
            )
        )
    return inputs.cache[key]


def header(inputs: MeasureInputs, request: MeasureRequest) -> pl.DataFrame:
    """One row per claim with its attributes (UNKNOWN when claims is not loaded), the
    header dates, and the origin period label by the origin axis (CV04): the month of the
    first valuation (a proxy) when the claim has no header or no date for the axis."""
    key = ("header", request.period, inputs.origin_axis)
    if key in inputs.cache:
        return inputs.cache[key]
    first = first_rows(inputs)
    claims = inputs.feeds.get("claims")
    base = first.select("claim_id", "first_valuation")
    if claims is not None:
        present = [c for c in ATTRIBUTES if c in claims.columns]
        claims = claims.unique(subset="claim_id", keep="first", maintain_order=True)
        base = base.join(
            claims.select("claim_id", *present, pl.col(REF).alias("claims_ref")),
            on="claim_id",
            how="left",
        )
    for name in ATTRIBUTES:
        if name not in base.columns:
            dtype = pl.Date if name.endswith("_date") else pl.String
            base = base.with_columns(pl.lit(None, dtype).alias(name))
    if "claims_ref" not in base.columns:
        base = base.with_columns(pl.lit(None, pl.UInt32).alias("claims_ref"))
    base = base.with_columns([pl.col(c).fill_null(UNKNOWN) for c in HEADER_DIMS])
    axis_field = {
        "accident": "occurrence_date",
        "report": "report_date",
    }.get(inputs.origin_axis)
    if inputs.origin_axis == "underwriting":
        policies = inputs.feeds.get("policies")
        if policies is not None and claims is not None and "policy_id" in claims.columns:
            start = policies.unique(subset="policy_id", keep="first").select(
                "policy_id", pl.col("start_date").alias("_axis")
            )
            linked = claims.select("claim_id", "policy_id").join(start, on="policy_id", how="left")
            base = base.join(linked.select("claim_id", "_axis"), on="claim_id", how="left")
        else:
            base = base.with_columns(pl.lit(None, pl.Date).alias("_axis"))
    elif axis_field is not None:
        base = base.with_columns(pl.col(axis_field).alias("_axis"))
    else:
        base = base.with_columns(pl.lit(None, pl.Date).alias("_axis"))
    origin_date = pl.col("_axis").fill_null(pl.col("first_valuation"))
    base = base.with_columns(
        origin_date.alias("origin_date"), pl.col("_axis").is_null().alias("origin_proxy")
    )
    base = add_period(
        base, "origin_date", "origin_period", request.period, inputs.fiscal_year_start_month
    )
    inputs.cache[key] = base
    return base


def size_classes(inputs: MeasureInputs, request: MeasureRequest) -> tuple[pl.DataFrame, list[str]]:
    """Each claim's class for the run (CV08): CATASTROPHE with an event code, else LARGE at or
    above the threshold of its segment and line, else ATTRITIONAL. Returns claim_id,
    claim_size_class, size, and the notes (groups without a LARGE class)."""
    key = ("classes", request.period)
    if key in inputs.cache:
        return inputs.cache[key]
    indexed = (
        inputs.market is not None and inputs.market.index(inputs.price_index or "") is not None
    )
    basis = Basis(
        ReinsuranceBasis.GROSS,
        CurrencyView.REPORTING,
        ValueBasis.INFLATION_ADJUSTED if indexed else ValueBasis.NOMINAL,
    )
    try:
        states, _ = amounts_at(inputs, basis, "incurred", [inputs.cut_off])
    except ConversionError:  # a missing rate or index: the size is nominal, as the spec allows
        states, _ = amounts_at(inputs, Basis(), "incurred", [inputs.cut_off])
    states, _ = left_out(states)
    head = header(inputs, request).select("claim_id", "segment", "line", "event_code")
    sized = states.select("claim_id", "status", pl.col("value").alias("size")).join(
        head, on="claim_id", how="left"
    )
    event = pl.col("event_code").is_not_null() & (pl.col("event_code") != UNKNOWN)
    pool = sized.filter(pl.col("status") != NIL)
    minimum = inputs.min_claims_for_percentile
    p = inputs.large_loss_percentile
    fixed = pl.DataFrame(
        [(s, line, t) for (s, line), t in inputs.large_loss_thresholds.items()],
        schema={"segment": pl.String, "line": pl.String, "t_fixed": pl.Float64},
        orient="row",
    )
    by_line = (
        pool.group_by("segment", "line")
        .agg(pl.len().alias("n"), pl.col("size").quantile(p, "linear").alias("t_line"))
        .filter(pl.col("n") >= minimum)
        .drop("n")
    )
    by_segment = (
        pool.group_by("segment")
        .agg(pl.len().alias("n"), pl.col("size").quantile(p, "linear").alias("t_segment"))
        .filter(pl.col("n") >= minimum)
        .drop("n")
    )
    sized = (
        sized.join(fixed, on=["segment", "line"], how="left")
        .join(by_line, on=["segment", "line"], how="left")
        .join(by_segment, on="segment", how="left")
        .with_columns(pl.coalesce("t_fixed", "t_line", "t_segment").alias("threshold"))
    )
    classed = sized.with_columns(
        pl.when(event)
        .then(pl.lit(CATASTROPHE))
        .when(pl.col("threshold").is_not_null() & (pl.col("size") >= pl.col("threshold")))
        .then(pl.lit(LARGE))
        .otherwise(pl.lit(ATTRITIONAL))
        .alias("claim_size_class")
    )
    notes = []
    without = (
        classed.filter(pl.col("threshold").is_null())
        .select("segment", "line")
        .unique()
        .sort("segment", "line")
    )
    if without.height:
        names = ", ".join(f"{s} / {line}" for s, line in without.iter_rows())
        notes.append(f"no LARGE class for {names}: fewer than {minimum} non-nil claims (CV08)")
    result = (classed.select("claim_id", "claim_size_class", "size", "threshold"), notes)
    inputs.cache[key] = result
    return result


def with_dimensions(
    frame: pl.DataFrame,
    dims: Sequence[str],
    inputs: MeasureInputs,
    request: MeasureRequest,
) -> tuple[pl.DataFrame, list[str]]:
    """Add the claim-level breakdown columns in `dims` to `frame` (which has claim_id):
    claims attributes, origin_period and claim_size_class. Other dimensions come from the
    rows the measure reads."""
    wanted = [d for d in dims if d in (*HEADER_DIMS, "origin_period") and d not in frame.columns]
    notes: list[str] = []
    if wanted:
        head = header(inputs, request).select("claim_id", *wanted)
        frame = frame.join(head, on="claim_id", how="left")
    if "claim_size_class" in dims and "claim_size_class" not in frame.columns:
        classes, class_notes = size_classes(inputs, request)
        frame = frame.join(
            classes.select("claim_id", "claim_size_class"), on="claim_id", how="left"
        )
        notes += class_notes
    return frame, notes


def last_day(month: int) -> date:
    return month_end(month)
