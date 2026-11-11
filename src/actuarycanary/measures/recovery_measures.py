"""RC03 recovery delay and RC04 recovery development ratio, on the recovery flows of a run:
the bookings of the recoveries feed, or the flows derived from the to-date fields of claim
valuations when there is no feed (decision 0203, records 0384 and 0386)."""

from datetime import date

import polars as pl

from actuarycanary.canonical.feeds import UNMAPPED
from actuarycanary.canonical.recoveries import DERIVED, OTHER, Recoveries, build_recoveries
from actuarycanary.convert import bases
from actuarycanary.convert.bases import RowBasis, ValueBasis
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.measures.claim_base import header
from actuarycanary.measures.claim_counts import MIN_FOR_PERCENTILES, _quantiles
from actuarycanary.measures.common import add_period
from actuarycanary.measures.model import (
    NOTE,
    REF,
    REFS_PREFIX,
    VALUE,
    Computed,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.periods import month_end, month_index, period_start

NO_DATA = "no recovery data"
TOTAL = "TOTAL"
VALUATIONS = "claim_valuations"
_CUMULATIVE = "subrogation_to_date"  # a flow component of convert.bases, used as the carrier


def recoveries_of(inputs: MeasureInputs) -> Recoveries:
    """The recovery flows of the run up to the cut-off, built once per run."""
    key = ("recoveries",)
    if key not in inputs.cache:
        valuations = inputs.feeds[VALUATIONS].filter(pl.col("valuation_date") <= inputs.cut_off)
        built = build_recoveries(inputs.feeds.get("recoveries"), valuations)
        frame = built.frame.filter(pl.col("booking_date") <= inputs.cut_off)
        inputs.cache[key] = Recoveries(frame, built.source, built.types, built.note, built.findings)
    return inputs.cache[key]


def _concept(recoveries: Recoveries) -> str:
    """The feed the `_ref` of a flow points to."""
    return VALUATIONS if recoveries.source == DERIVED else "recoveries"


def _source_notes(recoveries: Recoveries) -> list[str]:
    notes = [f"source: {recoveries.note}"]
    if OTHER not in recoveries.types:
        notes.append("the total is subrogation plus salvage only (no recoveries feed)")
    return notes


def _typed(flows: pl.DataFrame, by_type: bool) -> tuple[pl.DataFrame, list[str]]:
    """Flows with `recovery_type`; in a view by type a booking whose type has no class is left
    out (DV-RCV-02: it counts in the total and in no measure by type)."""
    flows = flows.with_columns(pl.col("type").alias("recovery_type"))
    unmapped = flows.filter(pl.col("type") == UNMAPPED).height
    if not by_type or unmapped == 0:
        return flows, []
    return (
        flows.filter(pl.col("type") != UNMAPPED),
        [f"{unmapped} bookings with a type outside the classes are in no view by type"],
    )


# --- RC03 ---------------------------------------------------------------------------------


def first_payments(inputs: MeasureInputs) -> pl.DataFrame:
    """claim_id and the month end of the valuation in which paid_to_date first rose above zero."""
    rows = inputs.feeds[VALUATIONS].filter(
        (pl.col("valuation_date") <= inputs.cut_off) & (pl.col("paid_to_date") > 0)
    )
    return rows.group_by("claim_id").agg(
        pl.col("valuation_date").min().dt.month_end().alias("first_payment")
    )


def recovery_delay(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RC03: days from the first payment of a claim to each recovery booked on it; the mean is
    the value, the median and the 90th percentile stand beside it."""
    recoveries = recoveries_of(inputs)
    if not recoveries.available:
        return Missing(NO_DATA)
    keys = list(request.breakdowns)
    concept = _concept(recoveries)
    flows, notes = _typed(recoveries.frame, "recovery_type" in keys)
    reversals = flows.filter(pl.col("amount") <= 0).height
    flows = flows.filter(pl.col("amount") > 0)
    if reversals:
        notes.append(f"{reversals} reversals (amounts not positive) are no recoveries: left out")
    flows = flows.join(first_payments(inputs), on="claim_id", how="left").with_columns(
        (pl.col("booking_date") - pl.col("first_payment")).dt.total_days().alias("delay")
    )
    early = flows.filter(pl.col("delay").is_null() | (pl.col("delay") < 0)).height
    flows = flows.filter(pl.col("delay") >= 0)
    if early:
        notes.append(
            f"{early} recoveries booked before the first payment of their claim, or on a claim "
            "never paid: kept out of the statistics"
        )
    if recoveries.source == DERIVED:
        notes.append("derived flows: delays are whole months between month ends")
    head = header(inputs, request)
    wanted = [k for k in ("segment", "line", "origin_period") if k in keys]
    if wanted:
        flows = flows.join(head.select("claim_id", *wanted), on="claim_id", how="left")
        flows = flows.with_columns(pl.col(k).fill_null("UNKNOWN") for k in wanted)
    if "calendar_period" in keys:
        flows = add_period(
            flows, "booking_date", "calendar_period", request.period, inputs.fiscal_year_start_month
        )
    parts = flows.partition_by(keys, as_dict=True, maintain_order=True) if keys else {(): flows}
    rows: list[dict[str, object]] = []
    for key, part in parts.items():
        delays, n = part["delay"], part.height
        row: dict[str, object] = dict(zip(keys, key, strict=True))
        row["n"] = n
        row[VALUE] = float(delays.mean()) if n else None  # type: ignore[arg-type]
        row["p50"] = _quantiles(delays, (0.5,))[0]
        row["p90"] = _quantiles(delays, (0.9,))[0] if n >= MIN_FOR_PERCENTILES else None
        row[NOTE] = "" if n else "no recovery with a delay: not computed"
        row[REFS_PREFIX + concept] = part[REF].unique().sort().to_list()
        rows.append(row)
    schema = {
        **{k: pl.String for k in keys},
        "n": pl.Int64,
        VALUE: pl.Float64,
        "p50": pl.Float64,
        "p90": pl.Float64,
        NOTE: pl.String,
        REFS_PREFIX + concept: pl.List(pl.UInt32),
    }
    frame = pl.DataFrame(rows, schema=schema)
    notes.append(f"the 90th percentile needs at least {MIN_FOR_PERCENTILES} recoveries")
    return Computed(
        frame.sort(keys) if keys else frame, (*_source_notes(recoveries), *notes), (concept,)
    )


# --- RC04 ---------------------------------------------------------------------------------


def _restated(flows: pl.DataFrame, inputs: MeasureInputs, request: MeasureRequest) -> pl.DataFrame:
    """Flows with `value`: the amount on the currency and value basis of the request, null
    where no rate or index applied. The cumulative amounts of each claim and type are restated
    by `convert.bases` like the to-date fields of a valuation row, and differenced again."""
    basis = request.basis
    if basis.currency is CurrencyView.ORIGINAL:
        if basis.value is ValueBasis.INFLATION_ADJUSTED:
            raise bases.BasisUnavailableError(
                "inflation adjustment needs the reporting currency view: the index belongs to "
                "the reporting currency (CV02)"
            )
        return flows.with_columns(pl.col("amount").alias(VALUE))
    row_basis = RowBasis(
        inputs.reporting_currency,
        basis.value,
        inputs.rates,
        inputs.market,
        inputs.price_index,
        inputs.value_date or inputs.cut_off,
    )
    over = ["claim_id", "type"]
    rows = flows.sort(*over, "booking_date", SOURCE_ROW).with_columns(
        pl.col("amount").cum_sum().over(over).alias(_CUMULATIVE),
        pl.col("booking_date").alias("valuation_date"),
        pl.col("claim_id").alias("_claim"),
        pl.concat_str("claim_id", "type", separator="|").alias("claim_id"),
    )
    restated, _ = bases.restate_rows(rows, [_CUMULATIVE], row_basis)
    level = pl.col(bases.RESTATED + _CUMULATIVE)
    return restated.with_columns(
        pl.when(pl.col("ok_flow"))
        .then(level - level.shift(1).over("claim_id").fill_null(0.0))
        .otherwise(None)
        .alias(VALUE),
        pl.col("_claim").alias("claim_id"),
    ).drop("_claim", _CUMULATIVE, bases.RESTATED + _CUMULATIVE, "valuation_date")


def _origin_starts(head: pl.DataFrame, inputs: MeasureInputs, request: MeasureRequest) -> dict:
    """Origin period label -> month index of its first month."""
    firsts = head.group_by("origin_period").agg(pl.col("origin_date").min())
    return {
        label: period_start(month_index(day), request.period, inputs.fiscal_year_start_month)
        for label, day in firsts.iter_rows()
        if isinstance(day, date)
    }


def recovery_development(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RC04: cumulative recoveries over cumulative paid, cell by cell of the paid triangle
    (MT01), for each recovery type and in total."""
    recoveries = recoveries_of(inputs)
    if not recoveries.available:
        return Missing(NO_DATA)
    triangles = inputs.triangles
    if triangles is None:
        return Missing("no triangles were built (MT01)")
    settings = triangles.settings
    if settings.value_basis is not request.basis.value:
        return Missing(
            f"the triangles are built on {settings.value_basis.value}, not on "
            f"{request.basis.value.value}"
        )
    keys = list(request.breakdowns)
    concept = _concept(recoveries)
    by_type = "recovery_type" in keys
    flows, notes = _typed(_restated(recoveries.frame, inputs, request), by_type)
    lost = flows.filter(pl.col(VALUE).is_null()).height
    if lost:
        notes.append(f"{lost} recovery bookings could not be converted or restated: left out")
    flows = flows.filter(pl.col(VALUE).is_not_null())
    head = header(inputs, request)
    known = flows.join(
        head.select("claim_id", "segment", "line", "origin_period"), on="claim_id", how="inner"
    )
    if known.height < flows.height:
        notes.append(
            f"{flows.height - known.height} recoveries on claims without a valuation are in no "
            "origin view"
        )
    starts = _origin_starts(head, inputs, request)
    kinds = [*recoveries.types, TOTAL] if by_type else [TOTAL]
    cells: list[dict[str, object]] = []
    for group in triangles.groups:
        paid = triangles.get("paid", group)
        of_group = known.filter((pl.col("segment") == group[0]) & (pl.col("line") == group[1]))
        for i, origin in enumerate(paid.origins):
            of_origin = of_group.filter(pl.col("origin_period").cast(pl.String) == str(origin))
            start = starts.get(origin)
            for j, age in enumerate(paid.ages):
                if not paid.observed[i, j] or start is None:
                    continue
                end = min(month_end(start + int(age) - 1), inputs.cut_off)
                upto = of_origin.filter(pl.col("booking_date") <= end)
                for kind in kinds:
                    part = upto if kind == TOTAL else upto.filter(pl.col("type") == kind)
                    cells.append(
                        {
                            "segment": group[0],
                            "line": group[1],
                            "recovery_type": kind,
                            "origin_period": str(origin),
                            "development_period": f"{age}",
                            "_age": int(age),
                            "_latest": bool(j == paid.latest_index[i]),
                            "numerator": float(part[VALUE].sum()),
                            "denominator": float(paid.cumulative[i, j]),
                            REFS_PREFIX + concept: part[REF].unique().sort().to_list(),
                        }
                    )
    schema = {
        "segment": pl.String,
        "line": pl.String,
        "recovery_type": pl.String,
        "origin_period": pl.String,
        "development_period": pl.String,
        "_age": pl.Int64,
        "_latest": pl.Boolean,
        "numerator": pl.Float64,
        "denominator": pl.Float64,
        REFS_PREFIX + concept: pl.List(pl.UInt32),
    }
    table = pl.DataFrame(cells, schema=schema)
    if not by_type:
        table = table.drop("recovery_type")
    if "development_period" not in keys:
        # cumulative amounts must not be added over development: the latest diagonal stands
        table = table.filter(pl.col("_latest"))
        notes.append("without development periods: the latest diagonal of each origin")
    refs = REFS_PREFIX + concept
    order = [*keys, "_age"] if "development_period" in keys else keys
    frame = (
        table.group_by(order, maintain_order=True).agg(
            pl.col("numerator").sum(),
            pl.col("denominator").sum(),
            pl.col(refs).list.explode(keep_nulls=False, empty_as_null=False).unique().sort(),
        )
        if keys
        else table.select(
            pl.col("numerator").sum(),
            pl.col("denominator").sum(),
            pl.col(refs)
            .list.explode(keep_nulls=False, empty_as_null=False)
            .unique()
            .sort()
            .implode(),
        )
    )
    positive = pl.col("denominator") > 0
    frame = frame.with_columns(
        pl.when(positive).then(pl.col("numerator") / pl.col("denominator")).alias(VALUE),
        pl.when(positive)
        .then(pl.lit(""))
        .otherwise(pl.lit("paid is zero: not computed"))
        .alias(NOTE),
    )
    if order:
        frame = frame.sort(order)
    frame = frame.select(*keys, VALUE, "numerator", "denominator", NOTE, refs)
    notes.append("cells of the paid triangle (MT01); recoveries booked up to the end of the cell")
    return Computed(frame, (*_source_notes(recoveries), *notes), (concept,))
