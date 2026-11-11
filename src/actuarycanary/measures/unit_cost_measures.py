"""Unit costs EX04 (administration cost per policy) and EX05 (claims-handling cost per claim),
per calendar period, nominal or at value-date prices (CV02; record 0387).

Expenses are shown at the level they were booked: a row without a line is in no view by line and
is never spread over lines. A month without expense rows is a missing booking, not a zero cost:
a period that holds such a month is not computed and the months are listed.
"""

from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import polars as pl

from actuarycanary.convert.bases import BasisUnavailableError, ValueBasis
from actuarycanary.convert.inflation import restatement_factors
from actuarycanary.convert.market import month_of
from actuarycanary.measures.claim_amounts import flow_frame
from actuarycanary.measures.claim_counts import settlement_rate
from actuarycanary.measures.common import group_agg, periods_between, refs
from actuarycanary.measures.expense_measures import EXPENSES, UNALLOCATED, _expense_rows
from actuarycanary.measures.model import (
    NOTE,
    REFS_PREFIX,
    VALUE,
    Computed,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.periods import Period, month_end

ADMINISTRATION = "ADMINISTRATION"
POLICIES = "policies"
VALUATIONS = "claim_valuations"
PERIOD = "calendar_period"
PER_PERIOD = "{} is a cost per calendar period: ask for the calendar_period breakdown"
SEVERAL_CURRENCIES = (
    "expenses in several currencies cannot be added in the ORIGINAL currency view: not computed"
)


def valued_expenses(
    inputs: MeasureInputs, request: MeasureRequest, types: Sequence[str]
) -> tuple[pl.DataFrame, list[str]]:
    """Expense rows of `types` on the basis of the request: converted like EX02 (CV01) and, on
    the inflation-adjusted basis, restated to value-date prices with the price index of their
    month (CV02). Rows without an index value are left out and counted in a note."""
    rows, notes = _expense_rows(inputs, request, types)
    if request.basis.value is not ValueBasis.INFLATION_ADJUSTED:
        return rows, notes
    if request.basis.currency is CurrencyView.ORIGINAL:
        raise BasisUnavailableError(
            "inflation adjustment needs the reporting currency view: the index belongs to the "
            "reporting currency (CV02)"
        )
    if inputs.market is None or inputs.price_index is None:
        raise BasisUnavailableError("value-date prices need a price index in market data (CV02)")
    value_date = inputs.value_date or inputs.cut_off
    rows = rows.with_columns(month_of("period").alias("_month"))
    factors = restatement_factors(inputs.market, inputs.price_index, value_date, rows["_month"])
    rows = rows.join(
        factors.select(pl.col("month").alias("_month"), pl.col("factor").alias("_factor")),
        on="_month",
        how="left",
    )
    lost = rows.filter(pl.col("_factor").is_null()).height
    if lost:
        notes.append(f"{lost} expense rows without a value of {inputs.price_index}: not restated")
    rows = rows.filter(pl.col("_factor").is_not_null()).with_columns(
        (pl.col("amount") * pl.col("_factor")).alias("amount")
    )
    notes.append(f"at prices of {value_date} ({inputs.price_index})")
    return rows.drop("_month", "_factor"), notes


def _periods(
    inputs: MeasureInputs, request: MeasureRequest
) -> list[tuple[str, date, date, list[int]]]:
    """(label, first day, last day, months) of the calendar periods the expense file spans, up to
    the cut-off; `months` are the month indices of the period inside that span."""
    dates = inputs.feeds[EXPENSES].filter(pl.col("period") <= inputs.cut_off)["period"]
    first, last = dates.min(), dates.max()
    if not isinstance(first, date) or not isinstance(last, date):
        return []
    low, high = 12 * first.year + first.month - 1, 12 * last.year + last.month - 1
    out = []
    for label, start, end in periods_between(
        first, last, request.period, inputs.fiscal_year_start_month
    ):
        months = [m for m in range(start, start + request.period.months) if low <= m <= high]
        first_day = date(start // 12, start % 12 + 1, 1)
        out.append((label, first_day, min(end, month_end(high)), months))
    return out


def _numerator(
    rows: pl.DataFrame, keys: list[str], periods: list[tuple[str, date, date, list[int]]]
) -> pl.DataFrame:
    """Expense amount per group and period on the full grid of the periods: `numerator` is empty
    where a month of the period has no expense row, and `_gaps` names those months."""
    levels = [k for k in keys if k != PERIOD]
    monthly = rows.with_columns(month_of("period").alias("_month"))
    booked = group_agg(
        monthly,
        keys,
        [
            pl.col("amount").sum().alias("_amount"),
            pl.col("_month").unique().alias("_months"),
            refs(EXPENSES, "expense_ref"),
        ],
    )
    wanted = pl.DataFrame(
        {PERIOD: [p[0] for p in periods], "_wanted": [p[3] for p in periods]},
        schema={PERIOD: pl.String, "_wanted": pl.List(pl.Int64)},
    )
    grid = (
        booked.select(levels).unique(maintain_order=True).join(wanted, how="cross")
        if levels
        else wanted
    )
    frame = grid.join(booked, on=keys, how="left").with_columns(
        pl.col("_wanted")
        .list.set_difference(pl.col("_months").fill_null([]).cast(pl.List(pl.Int64)))
        .list.sort()
        .alias("_missing")
    )
    labels = pl.col("_missing").list.eval(
        pl.format(
            "{}-{}",
            pl.element() // 12,
            (pl.element() % 12 + 1).cast(pl.String).str.zfill(2),
        )
    )
    return frame.with_columns(
        pl.when(pl.col("_missing").list.len() == 0).then(pl.col("_amount")).alias("numerator"),
        labels.list.join(", ").alias("_gaps"),
        pl.col(REFS_PREFIX + EXPENSES).fill_null([]),
    ).drop("_amount", "_months", "_wanted", "_missing")


def _one_currency(rows: pl.DataFrame, request: MeasureRequest) -> bool:
    return (
        request.basis.currency is not CurrencyView.ORIGINAL
        or rows["currency"].drop_nulls().n_unique() <= 1
    )


def _finish(frame: pl.DataFrame, keys: list[str], no_denominator: str, what: str) -> pl.DataFrame:
    positive = pl.col("denominator") > 0
    known = pl.col("numerator").is_not_null()
    frame = frame.with_columns(pl.col("denominator").fill_null(0.0)).with_columns(
        pl.when(known & positive).then(pl.col("numerator") / pl.col("denominator")).alias(VALUE),
        pl.when(~known)
        .then(pl.format("no {} expense rows in {}: not computed", pl.lit(what), "_gaps"))
        .when(~positive)
        .then(pl.lit(no_denominator))
        .otherwise(pl.lit(""))
        .alias(NOTE),
    )
    rest = [c for c in frame.columns if c.startswith(REFS_PREFIX) or c == "components"]
    return frame.select(*keys, VALUE, "numerator", "denominator", NOTE, *rest).sort(
        keys, nulls_last=True
    )


# --- EX04 ---------------------------------------------------------------------------------


def _policy_days(starts: np.ndarray, ends: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    """Policy days of cover before each day of `bounds` (days since the epoch): the count in
    force is integrated over its changes at the start and end days."""
    days = np.concatenate([starts, ends])
    steps = np.concatenate([np.ones(len(starts)), -np.ones(len(ends))])
    order = np.argsort(days, kind="stable")
    days, steps = days[order], steps[order]
    count = np.cumsum(steps)  # in force from days[k] on
    spans = np.diff(days, append=days[-1]) if len(days) else np.array([])
    before = np.concatenate([[0.0], np.cumsum(count[:-1] * spans[:-1])]) if len(days) else days
    at = np.searchsorted(days, bounds, side="right") - 1
    inside = at >= 0
    k = np.clip(at, 0, max(len(days) - 1, 0))
    if len(days) == 0:
        return np.zeros(len(bounds))
    return np.where(inside, before[k] + count[k] * (bounds - days[k]), 0.0)


def policies_in_force(
    inputs: MeasureInputs,
    levels: list[str],
    periods: list[tuple[str, date, date, list[int]]],
) -> pl.DataFrame:
    """Average number of policies in force per group and period: the policy days of cover in
    the period over its days. Cover is [start_date, end_date) and ends at the cancellation date
    when there is one (CV04)."""
    policies = inputs.feeds[POLICIES].filter(
        pl.col("start_date").is_not_null() & pl.col("end_date").is_not_null()
    )
    end = (
        pl.min_horizontal("end_date", pl.col("cancellation_date").fill_null(pl.col("end_date")))
        if "cancellation_date" in policies.columns
        else pl.col("end_date")
    )
    cover = policies.unique(subset="policy_id", keep="first", maintain_order=True).select(
        *levels,
        pl.col("start_date").to_physical().cast(pl.Int64).alias("_start"),
        pl.max_horizontal(end, "start_date").to_physical().cast(pl.Int64).alias("_end"),
    )
    epoch = date(1970, 1, 1)
    firsts = np.array([(p[1] - epoch).days for p in periods], dtype=float)
    lasts = np.array([(p[2] + timedelta(days=1) - epoch).days for p in periods], dtype=float)
    parts = cover.partition_by(levels, as_dict=True, maintain_order=True) if levels else {(): cover}
    out = []
    for key, part in parts.items():
        starts, ends = (
            part["_start"].to_numpy().astype(float),
            part["_end"].to_numpy().astype(float),
        )
        days = _policy_days(starts, ends, lasts) - _policy_days(starts, ends, firsts)
        out.append(
            pl.DataFrame(
                {
                    **{
                        name: [value] * len(periods)
                        for name, value in zip(levels, key, strict=True)
                    },
                    PERIOD: [p[0] for p in periods],
                    "denominator": (days / (lasts - firsts)).tolist(),
                },
                schema_overrides={name: pl.String for name in levels},
            )
        )
    return (
        pl.concat(out)
        if out
        else pl.DataFrame(schema={PERIOD: pl.String, "denominator": pl.Float64})
    )


def administration_cost_per_policy(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """EX04: administration expenses of a period over the average policies in force in it."""
    keys = list(request.breakdowns)
    if PERIOD not in keys:
        return Missing(PER_PERIOD.format("EX04"))
    if not (inputs.feeds[EXPENSES]["type"] == ADMINISTRATION).any():
        return Missing("no administration expenses in the expense file")
    levels = [k for k in keys if k != PERIOD]
    absent = [k for k in levels if k not in inputs.feeds[POLICIES].columns]
    if absent:
        return Missing(f"policies carry no {', '.join(absent)}: no cost per policy at that level")
    rows, notes = valued_expenses(inputs, request, (ADMINISTRATION,))
    if not _one_currency(rows, request):
        return Missing(SEVERAL_CURRENCIES)
    periods = _periods(inputs, request)
    top = _numerator(rows, keys, periods)
    bottom = policies_in_force(inputs, levels, periods)
    frame = top.join(bottom, on=keys, how="left")
    frame = _finish(
        frame, keys, "no policies in force in the period: not computed", "administration"
    )
    notes.append("lineage: the expense rows; the denominator counts every policy in force")
    return Computed(frame, tuple(notes), (EXPENSES,))


# --- EX05 ---------------------------------------------------------------------------------


def claims_handling_cost_per_claim(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """EX05: allocated claim expense flows plus unallocated claims-handling expenses of a period
    over the claims handled in it (open at its start plus reported in it, as CL09)."""
    keys = list(request.breakdowns)
    if PERIOD not in keys:
        return Missing(PER_PERIOD.format("EX05"))
    notes: list[str] = []
    periods = _periods(inputs, request)
    labels = [p[0] for p in periods]
    components: list[str] = []
    allocated = None
    try:
        flows, flow_notes = flow_frame(inputs, request, "expense_allocated", "allocated expense")
        flows = flows.filter(pl.col(PERIOD).is_in(labels))
        allocated = group_agg(
            flows, keys, [pl.col(VALUE).sum().alias("_allocated"), refs(VALUATIONS)]
        )
        notes += flow_notes
        components.append("allocated")
    except BasisUnavailableError:
        notes.append("no allocated claims expense column in claim_valuations: unallocated only")
    frame = None
    if (inputs.feeds[EXPENSES]["type"] == UNALLOCATED).any():
        rows, expense_notes = valued_expenses(inputs, request, (UNALLOCATED,))
        if not _one_currency(rows, request):
            return Missing(SEVERAL_CURRENCIES)
        frame = _numerator(rows, keys, periods).rename({"numerator": "_unallocated"})
        notes += expense_notes
        components.append("unallocated")
    if not components:
        return Missing(
            "neither allocated claims expense in claim_valuations nor "
            f"{UNALLOCATED} expenses were loaded"
        )
    if frame is None:
        assert allocated is not None
        frame = allocated.with_columns(pl.lit("").alias("_gaps"))
        frame = frame.with_columns(pl.col("_allocated").alias("numerator"))
        notes.append(f"no {UNALLOCATED} expenses in the expense file: allocated only")
    elif allocated is not None:
        frame = frame.join(allocated, on=keys, how="left").with_columns(
            (pl.col("_unallocated") + pl.col("_allocated").fill_null(0.0)).alias("numerator")
        )
    else:
        frame = frame.with_columns(pl.col("_unallocated").alias("numerator"))
    label = "allocated and unallocated" if len(components) == 2 else f"{components[0]} only"
    frame = frame.with_columns(pl.lit(label).alias("components"))

    counts = settlement_rate(
        spec, inputs, MeasureRequest(tuple(keys), request.period, request.basis)
    )
    assert isinstance(counts, Computed)
    handled = counts.frame.select(*keys, "denominator", pl.col(NOTE).alias("_count_note"))
    frame = frame.join(handled, on=keys, how="left")
    first = period_label_of_first_valuation(inputs, request.period)
    frame = _finish(
        frame.with_columns(pl.col("denominator").cast(pl.Float64)),
        keys,
        "no claims handled in the period: not computed",
        "unallocated claims-handling",
    ).with_columns(
        pl.when(pl.col(PERIOD) == first).then(None).otherwise(pl.col(VALUE)).alias(VALUE),
        pl.when(pl.col(PERIOD) == first)
        .then(pl.lit("first period of the file: the open count at its start is unknown"))
        .otherwise(pl.col(NOTE))
        .alias(NOTE),
    )
    return Computed(
        frame,
        tuple(notes),
        tuple(c for c in (VALUATIONS, EXPENSES) if REFS_PREFIX + c in frame.columns),
    )


def period_label_of_first_valuation(inputs: MeasureInputs, period: Period) -> str:
    first = inputs.feeds[VALUATIONS]["valuation_date"].min()
    assert isinstance(first, date)
    (label, _, _), *_ = periods_between(first, first, period, inputs.fiscal_year_start_month)
    return label
