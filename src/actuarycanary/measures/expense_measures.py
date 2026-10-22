"""Expense measures EX01 to EX03 (blueprint 8.1, decision 0051).

Expenses exist on the gross basis only (CV03). Commission is earned like premium (PR02);
expense rows are flows of the day their period starts, converted by CV01.
"""

from collections.abc import Sequence

import polars as pl

from actuarycanary.convert.bases import BasisUnavailableError
from actuarycanary.convert.currency import Rule, convert
from actuarycanary.measures.claim_amounts import flow_frame
from actuarycanary.measures.common import (
    add_period,
    group_agg,
    keep_columns,
    note_when,
    ratio_frame,
    refs,
    span_labels,
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
from actuarycanary.measures.premium_measures import earned_rolled, group_keys, left_over_notes
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.premium import PremiumError

EXPENSES = "expenses"
PREMIUMS = "premiums"
POLICIES = "policies"
CONCEPT = "claim_valuations"
COMMISSION = "COMMISSION"
RATIO_TYPES = ("ACQUISITION", "ADMINISTRATION")
UNALLOCATED = "CLAIMS_HANDLING_UNALLOCATED"
LEVELS = ("segment", "line", "entity")  # what expense rows may carry


def _positive(frame: pl.DataFrame, text: str) -> pl.DataFrame:
    return frame.with_columns(
        note_when(pl.col("denominator") <= 0, text).alias(NOTE),
    )


def commission_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """EX01: commission earned like premium over gross earned premium."""
    if not (inputs.feeds[PREMIUMS]["type"] == COMMISSION).any():
        return Missing("no commission in the premium file")
    keys = group_keys(request)
    try:
        commission, notes = earned_rolled(inputs, request, transaction_types=(COMMISSION,))
        premium, more = earned_rolled(inputs, request)
    except PremiumError as error:
        return Missing(str(error))
    frame = ratio_frame(commission, premium, keys, ("refs_premiums", "refs_policies"))
    frame = _positive(frame, "earned premium is zero or negative: not computed")
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple(dict.fromkeys([*notes, *more])),
        (PREMIUMS, POLICIES),
    )


def _expense_rows(
    inputs: MeasureInputs,
    request: MeasureRequest,
    types: Sequence[str],
) -> tuple[pl.DataFrame, list[str]]:
    """Expense rows of `types` up to the cut-off in the reporting currency (CV01 flows), with the
    calendar period of their period date. Rows without a value for a requested level are left
    out: expenses are not allocated to levels they do not carry."""
    rows = inputs.feeds[EXPENSES].filter(
        pl.col("type").is_in(list(types)) & (pl.col("period") <= inputs.cut_off)
    )
    notes: list[str] = []
    for level in LEVELS:
        if level in request.breakdowns:
            if level not in rows.columns:
                rows = rows.head(0).with_columns(pl.lit(None, pl.String).alias(level))
                notes.append(f"expense rows carry no {level}: no ratio at that level")
                continue
            unallocated = rows.filter(pl.col(level).is_null()).height
            if unallocated:
                notes.append(
                    f"{unallocated} expense rows without {level} not allocated: the ratio covers "
                    f"only expenses that carry a {level}"
                )
            rows = rows.filter(pl.col(level).is_not_null())
    if request.basis.currency is CurrencyView.REPORTING:
        done = convert(
            rows,
            ["amount"],
            day="period",
            rule=Rule.FLOW,
            target=inputs.reporting_currency,
            market=inputs.market,
        )
        notes += left_over_notes(done.not_converted)
        rows = done.frame.filter(pl.col("rate").is_not_null()).with_columns(
            pl.lit(inputs.reporting_currency).alias("currency")
        )
    rows = add_period(
        rows, "period", "calendar_period", request.period, inputs.fiscal_year_start_month
    ).with_columns(pl.col("type").alias("expense_type"))
    return rows.with_columns(pl.col(REF).alias("expense_ref")), notes


def expense_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """EX02: acquisition and administration expenses over gross earned premium."""
    rows, notes = _expense_rows(inputs, request, RATIO_TYPES)
    if not (inputs.feeds[EXPENSES]["type"].is_in(RATIO_TYPES)).any():
        return Missing("no acquisition or administration expenses in the expense file")
    keys = group_keys(request)
    top = group_agg(
        rows,
        keys,
        [pl.col("amount").sum().alias(VALUE), refs(EXPENSES, "expense_ref")],
    )
    try:
        plain = [k for k in keys if k != "expense_type"]
        premium, more = earned_rolled(
            inputs,
            MeasureRequest(
                tuple(k for k in request.breakdowns if k != "expense_type"),
                request.period,
                request.basis,
            ),
        )
    except PremiumError as error:
        return Missing(str(error))
    frame = ratio_frame_on(top, premium, keys, plain)
    if "calendar_period" in keys:  # periods outside the expense file are missing, not zero
        dates = inputs.feeds[EXPENSES]["period"]
        frame = frame.filter(
            pl.col("calendar_period").is_in(
                span_labels(
                    dates.min(), dates.max(), request.period, inputs.fiscal_year_start_month
                )
            )
        )
    frame = _positive(frame, "earned premium is zero or negative: not computed")
    notes.append("OTHER and CLAIMS_HANDLING_UNALLOCATED expenses are not part of the ratio")
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple([*notes, *more]),
        (EXPENSES, PREMIUMS, POLICIES),
    )


def ratio_frame_on(
    top: pl.DataFrame, bottom: pl.DataFrame, keys: Sequence[str], shared: Sequence[str]
) -> pl.DataFrame:
    """`top` over `bottom` when `top` has keys (an expense type) that `bottom` does not carry."""
    lineage = ("refs_expenses", "refs_premiums", "refs_policies")
    if list(keys) == list(shared):
        return ratio_frame(top, bottom, keys, lineage)
    other = bottom.rename({VALUE: "denominator"})
    joined = (
        top.join(other, on=list(shared), how="left") if shared else top.join(other, how="cross")
    )
    return joined.rename({VALUE: "numerator"}).with_columns(
        pl.col("denominator").fill_null(0.0),
        pl.when(pl.col("denominator") > 0)
        .then(pl.col("numerator") / pl.col("denominator"))
        .alias(VALUE),
    )


def claims_handling_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """EX03: allocated claim expense flows plus unallocated claims-handling expenses over paid
    flows, both components or the one that exists, labelled."""
    keys = group_keys(request)
    plain = [k for k in keys if k in ("segment", "line", "entity", "calendar_period")]
    notes: list[str] = []
    paid, paid_notes = flow_frame(inputs, request, "paid", "paid flows")
    notes += paid_notes
    denominator = group_agg(paid, keys, [pl.col(VALUE).sum(), refs(CONCEPT)])
    allocated = None
    components: list[str] = []
    try:
        rows, allocated_notes = flow_frame(
            inputs, request, "expense_allocated", "allocated expense"
        )
        allocated = group_agg(rows, keys, [pl.col(VALUE).sum().alias("allocated"), refs(CONCEPT)])
        notes += allocated_notes
        components.append("allocated")
    except BasisUnavailableError:
        notes.append("no allocated claims expense column in claim_valuations")
    unallocated = None
    if inputs.has(EXPENSES) and (inputs.feeds[EXPENSES]["type"] == UNALLOCATED).any():
        expense, expense_notes = _expense_rows(inputs, request, (UNALLOCATED,))
        unallocated = group_agg(
            expense,
            keys,
            [pl.col("amount").sum().alias("unallocated"), refs(EXPENSES, "expense_ref")],
        )
        notes += expense_notes
        components.append("unallocated")
    if not components:
        return Missing(
            "neither allocated claims expense in claim_valuations nor "
            f"{UNALLOCATED} expenses were loaded"
        )
    del plain
    frame = denominator.rename({VALUE: "denominator"})
    for part in (allocated, unallocated):
        if part is not None:
            frame = (
                frame.join(part, on=keys, how="full", coalesce=True, suffix="_part")
                if keys
                else pl.concat([frame, part], how="horizontal")
            )
    for column in ("allocated", "unallocated"):
        if column in frame.columns:
            frame = frame.with_columns(pl.col(column).fill_null(0.0))
    frame = frame.with_columns(pl.col("denominator").fill_null(0.0))
    numerator = pl.sum_horizontal(
        pl.col(c) for c in ("allocated", "unallocated") if c in frame.columns
    )
    label = {"allocated": "allocated only", "unallocated": "unallocated only"}.get(
        components[0] if len(components) == 1 else "", "allocated and unallocated"
    )
    frame = frame.with_columns(numerator.alias("numerator")).with_columns(
        pl.when(pl.col("denominator") > 0)
        .then(pl.col("numerator") / pl.col("denominator"))
        .alias(VALUE),
        *[
            pl.when(pl.col("denominator") > 0)
            .then(pl.col(c) / pl.col("denominator"))
            .alias(f"{c}_ratio")
            for c in components
        ],
        pl.lit(label).alias("components"),
        note_when(pl.col("denominator") <= 0, "paid is zero: not computed").alias(NOTE),
    )
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple(notes),
        (CONCEPT, EXPENSES),
    )
