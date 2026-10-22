"""Premium measures PR01 to PR06 (blueprint 8.1, decision 0051).

Premium amounts are signed transactions on a reinsurance basis, converted as flows at the rate
of their booking date and, on request, restated (CV01 to CV03, CV05). Earning is done by
`structures.premium`; this module chooses the grain, the breakdowns and the edge cases.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl

from actuarycanary.canonical.feeds import Finding
from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.measures.common import (
    add_period,
    group_agg,
    keep_columns,
    note_when,
    periods_between,
    ratio_columns,
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
from actuarycanary.structures.premium import (
    CEDED_TYPE,
    PremiumError,
    PremiumSettings,
    booked_transactions,
    earned_exposure,
    earned_premium,
    unearned_premium,
)

POLICY_DIMS = ("segment", "line", "entity", "product", "partner", "channel")
PREMIUMS = "premiums"
POLICIES = "policies"
RETURN_TYPES = ("CANCELLATION", "REFUND")
NEW_TYPES = ("WRITTEN", "ENDORSEMENT")


def policy_dims(request: MeasureRequest) -> list[str]:
    return [d for d in request.breakdowns if d in POLICY_DIMS]


def group_keys(request: MeasureRequest) -> list[str]:
    """The breakdown columns; the ORIGINAL view never adds currencies, so it groups by them."""
    keys = list(request.breakdowns)
    if request.basis.currency is CurrencyView.ORIGINAL and "currency" not in keys:
        keys.append("currency")
    return keys


def settings_for(
    inputs: MeasureInputs,
    request: MeasureRequest,
    basis: ReinsuranceBasis | None = None,
    **extra: Any,
) -> PremiumSettings:
    reporting = request.basis.currency is CurrencyView.REPORTING
    return PremiumSettings(
        period=request.period,
        fiscal_year_start_month=inputs.fiscal_year_start_month,
        cut_off=inputs.cut_off,
        reinsurance_basis=basis or request.basis.reinsurance,
        value_basis=request.basis.value,
        value_date=inputs.value_date,
        price_index=inputs.price_index or "CPI_TR",
        reporting_currency=inputs.reporting_currency if reporting else None,
        **extra,
    )


def finding_notes(findings: Sequence[Finding]) -> list[str]:
    return [f"{f.rule}: {f.message} ({f.count} rows)" for f in findings]


def left_over_notes(not_converted: pl.DataFrame, value: str = "amount") -> list[str]:
    """CV01: amounts without a rate are reported apart, in their own currency."""
    if not_converted.height == 0 or value not in not_converted.columns:
        return []
    parts = ", ".join(
        f"{row['currency']} {row[value]:,.0f}" for row in not_converted.iter_rows(named=True)
    )
    return [f"left out, no exchange rate (CV01): {parts} in original currency"]


def transactions_with_policies(
    inputs: MeasureInputs,
    request: MeasureRequest,
    basis: ReinsuranceBasis | None = None,
    **extra: Any,
) -> tuple[pl.DataFrame, list[str]]:
    """Premium transactions booked up to the cut-off on the basis, with the policy attributes
    of the requested breakdowns (UNKNOWN for a policy not in policies, DV-PRM-06), the calendar
    period of the booking date and the notes of the conversion."""
    settings = settings_for(inputs, request, basis, **extra)
    rows, not_converted, _, findings = booked_transactions(
        inputs.feeds[PREMIUMS], settings, inputs.market, inputs.cut_off
    )
    notes = [*finding_notes(findings), *left_over_notes(not_converted)]
    dims = policy_dims(request)
    if dims:
        if not inputs.has(POLICIES):
            raise PremiumError(f"breakdowns {', '.join(dims)} need policies, which are not loaded")
        policies = inputs.feeds[POLICIES]
        present = [d for d in dims if d in policies.columns]
        attached = policies.unique(subset="policy_id", keep="first").select(
            "policy_id", *present, pl.col(REF).alias("policy_ref")
        )
        rows = rows.join(attached, on="policy_id", how="left")
        rows = rows.with_columns(
            *[pl.col(d).fill_null("UNKNOWN") for d in present],
            *[pl.lit("UNKNOWN").alias(d) for d in dims if d not in present],
        )
    rows = add_period(
        rows, "booking_date", "calendar_period", request.period, inputs.fiscal_year_start_month
    )
    return rows, notes


def covered_periods(inputs: MeasureInputs, request: MeasureRequest) -> list[str]:
    """Labels of the periods from the first to the last booking month of the file, up to the
    cut-off (PR01: inside it a period without rows is 0, outside it is missing)."""
    premiums = inputs.feeds[PREMIUMS].filter(pl.col("booking_date") <= inputs.cut_off)
    first, last = premiums["booking_date"].min(), premiums["booking_date"].max()
    if not isinstance(first, date) or not isinstance(last, date):
        return []
    return [
        label
        for label, _, _ in periods_between(
            first, last, request.period, inputs.fiscal_year_start_month
        )
    ]


def _complete(
    frame: pl.DataFrame, keys: Sequence[str], periods: Sequence[str], zero: Sequence[str]
) -> pl.DataFrame:
    """Every group has a row for every covered period; a period without rows has the value 0."""
    if "calendar_period" not in keys:
        return frame
    others = [k for k in keys if k != "calendar_period"]
    groups = (
        frame.select(others).unique(maintain_order=True) if others else pl.DataFrame({"_": [0]})
    )
    grid = groups.join(pl.DataFrame({"calendar_period": list(periods)}), how="cross")
    full = grid.join(frame, on=[*others, "calendar_period"], how="left")
    full = full.with_columns([pl.col(c).fill_null(0.0) for c in zero])
    return full.drop("_", strict=False)


def _written_like(
    inputs: MeasureInputs,
    request: MeasureRequest,
    basis: ReinsuranceBasis | None = None,
) -> tuple[pl.DataFrame, list[str], tuple[str, ...]]:
    rows, notes = transactions_with_policies(inputs, request, basis)
    concepts = (PREMIUMS, POLICIES) if policy_dims(request) else (PREMIUMS,)
    return rows, notes, concepts


def _ref_aggs(concepts: Sequence[str]) -> list[pl.Expr]:
    aggs = [pl.col(REF).unique().sort().alias("refs_premiums")]
    if POLICIES in concepts:
        aggs.append(pl.col("policy_ref").drop_nulls().unique().sort().alias("refs_policies"))
    return aggs


def written_premium(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """PR01: signed premium of the written types booked in a period."""
    try:
        rows, notes, concepts = _written_like(inputs, request)
    except PremiumError as error:
        return Missing(str(error))
    keys = group_keys(request)
    frame = group_agg(rows, keys, [pl.col("amount").sum().alias(VALUE), *_ref_aggs(concepts)])
    if "calendar_period" in keys:
        frame = _complete(frame, keys, covered_periods(inputs, request), [VALUE])
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple(notes),
        concepts,
    )


def cancellation_rate(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """PR04: premium returned by cancellations and refunds over premium written before returns."""
    try:
        rows, notes, concepts = _written_like(inputs, request)
    except PremiumError as error:
        return Missing(str(error))
    keys = group_keys(request)
    frame = group_agg(
        rows,
        keys,
        [
            (pl.lit(0.0) - pl.col("amount").filter(pl.col("type").is_in(RETURN_TYPES)).sum()).alias(
                "numerator"
            ),
            pl.col("amount").filter(pl.col("type").is_in(NEW_TYPES)).sum().alias("denominator"),
            *_ref_aggs(concepts),
        ],
    )
    frame = frame.with_columns(
        *ratio_columns(),
        note_when(
            pl.col("denominator") <= 0, "premium written is zero or negative: not computed"
        ).alias(NOTE),
    )
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple(notes),
        concepts,
    )


def retention_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """PR05: net written premium over gross written premium."""
    premiums = inputs.feeds[PREMIUMS]
    if not (premiums["type"] == CEDED_TYPE).any():
        return Missing("no ceded premium in the premium file (CV03)")
    try:
        rows, notes, concepts = _written_like(inputs, request, ReinsuranceBasis.NET)
    except PremiumError as error:
        return Missing(str(error))
    keys = group_keys(request)
    ceded = pl.col("type") == CEDED_TYPE
    frame = group_agg(
        rows,
        keys,
        [
            pl.col("amount").sum().alias("numerator"),
            pl.col("amount").filter(~ceded).sum().alias("denominator"),
            *_ref_aggs(concepts),
        ],
    )
    frame = frame.with_columns(
        *ratio_columns(),
        pl.when(pl.col("denominator") <= 0)
        .then(pl.lit("gross written premium is zero or negative: not computed"))
        .when((pl.col("numerator") < 0) | (pl.col("numerator") > pl.col("denominator")))
        .then(
            pl.lit(
                "outside 0 to 1: ceded premium is probably booked in another period than the gross"
            )
        )
        .otherwise(pl.lit(""))
        .alias(NOTE),
    )
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple(notes),
        concepts,
    )


def _roll_up(frame: pl.DataFrame, keys: Sequence[str], values: Sequence[str]) -> pl.DataFrame:
    """Sum `values` over the columns not in `keys`, merging the lineage lists."""
    lists = [c for c in frame.columns if c in ("rows", "policy_rows")]
    return group_agg(
        frame,
        keys,
        [
            *[pl.col(v).sum() for v in values],
            *[pl.col(c).list.explode().unique().sort() for c in lists],
        ],
    )


def _earned(
    inputs: MeasureInputs, request: MeasureRequest, **extra: Any
) -> tuple[pl.DataFrame, list[str]]:
    """Earned premium by the requested policy dimensions, calendar period and currency."""
    dims = policy_dims(request)
    settings = settings_for(inputs, request, **extra)
    structure = earned_premium(
        inputs.feeds[PREMIUMS], inputs.feeds[POLICIES], settings, inputs.market, dims, REF
    )
    notes = [*finding_notes(structure.findings), *left_over_notes(structure.not_converted)]
    return structure.frame.rename({"period": "calendar_period"}), notes


def _earned_result(frame: pl.DataFrame, keys: Sequence[str], value: str) -> pl.DataFrame:
    rolled = _roll_up(frame.drop("period_number"), keys, [value]).rename(
        {value: VALUE, "rows": "refs_premiums", "policy_rows": "refs_policies"}
    )
    return keep_columns(rolled, keys).sort(keys, nulls_last=True) if keys else rolled


def earned_rolled(
    inputs: MeasureInputs, request: MeasureRequest, **extra: Any
) -> tuple[pl.DataFrame, list[str]]:
    """Earned premium on the breakdowns of `request`: the keys, `value` and the lineage."""
    frame, notes = _earned(inputs, request, **extra)
    keys = group_keys(request)
    return _earned_result(frame, keys, "earned_premium"), notes


def earned_premium_measure(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """PR02: written premium spread by day over the cover period."""
    try:
        frame, notes = _earned(inputs, request)
    except PremiumError as error:
        return Missing(str(error))
    keys = group_keys(request)
    return Computed(
        _earned_result(frame, keys, "earned_premium"), tuple(notes), (PREMIUMS, POLICIES)
    )


def unearned_premium_measure(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """PR03: premium booked to date that pays for cover after the valuation date."""
    settings = settings_for(inputs, request)
    dims = policy_dims(request)
    try:
        structure = unearned_premium(
            inputs.feeds[PREMIUMS],
            inputs.feeds[POLICIES],
            settings,
            inputs.cut_off,
            inputs.market,
            dims,
            REF,
        )
    except (PremiumError, ValueError) as error:
        return Missing(str(error))
    keys = group_keys(request)
    frame = structure.frame.rename(
        {"unearned_premium": VALUE, "rows": "refs_premiums", "policy_rows": "refs_policies"}
    )
    if "valuation_date" in keys:
        frame = frame.with_columns(pl.lit(inputs.cut_off).alias("valuation_date"))
    frame = _roll_up_unearned(frame, [k for k in keys if k != "valuation_date"], keys)
    notes = [
        *finding_notes(structure.findings),
        *left_over_notes(structure.not_converted, "unearned_premium"),
    ]
    return Computed(frame, tuple(notes), (PREMIUMS, POLICIES))


def _roll_up_unearned(
    frame: pl.DataFrame, group: Sequence[str], keys: Sequence[str]
) -> pl.DataFrame:
    if "valuation_date" in keys:
        group = [*group, "valuation_date"]
    rolled = group_agg(
        frame,
        group,
        [
            pl.col(VALUE).sum(),
            pl.col("refs_premiums").list.explode().unique().sort(),
            pl.col("refs_policies").list.explode().unique().sort(),
        ],
    )
    return keep_columns(rolled, keys).sort(keys, nulls_last=True) if keys else rolled


def average_premium(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """PR06: gross earned premium over earned exposure in the period."""
    dims = policy_dims(request)
    try:
        premium, notes = _earned(inputs, request)
    except PremiumError as error:
        return Missing(str(error))
    by_currency = request.basis.currency is CurrencyView.ORIGINAL
    exposure = earned_exposure(
        inputs.feeds[POLICIES],
        settings_for(inputs, request),
        inputs.cut_off,
        dims,
        REF,
        by_currency,
    ).rename({"period": "calendar_period"})
    keys = group_keys(request)
    on = [*dims, "calendar_period", *(["currency"] if by_currency else [])]
    premium = premium.drop("period_number")
    exposure = exposure.drop("period_number")
    if by_currency is False and "currency" in premium.columns:
        premium = _roll_up(premium, [*dims, "calendar_period"], ["earned_premium"])
    joined = premium.join(exposure, on=on, how="inner")
    group = [k for k in keys if k in joined.columns]
    summed = group_agg(
        joined,
        group,
        [
            pl.col("earned_premium").sum().alias("numerator"),
            pl.col("earned_exposure").sum().alias("denominator"),
            pl.col("rows").list.explode().unique().sort().alias("refs_premiums"),
            pl.col("policy_rows").list.explode().unique().sort().alias("refs_policies"),
        ],
    )
    frame = summed.with_columns(
        *ratio_columns(),
        note_when(pl.col("denominator") <= 0, "earned exposure is zero: not computed").alias(NOTE),
    )
    notes.append(
        "exposure units missing for some policies count 1 per policy-year (CV04)"
        if "exposure_units" not in inputs.feeds[POLICIES].columns
        else "policies without exposure_units count 1 unit per policy-year (CV04)"
    )
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True) if keys else frame,
        tuple(notes),
        (PREMIUMS, POLICIES),
    )
