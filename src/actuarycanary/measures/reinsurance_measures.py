"""Reinsurance measures RI01 cession ratio and RI02 reinsurance result (CV03, decision 0051)."""

import polars as pl

from actuarycanary.convert.bases import BasisUnavailableError, ReinsuranceBasis
from actuarycanary.measures.claim_amounts import (
    CONCEPT,
    incurred,
    origin_notes,
    prepared,
)
from actuarycanary.measures.claim_amounts import (
    group_keys as claim_keys,
)
from actuarycanary.measures.claim_base import amounts_at, left_out
from actuarycanary.measures.common import (
    group_agg,
    keep_columns,
    note_when,
    ratio_frame,
    refs,
)
from actuarycanary.measures.model import (
    NOTE,
    VALUE,
    Basis,
    Computed,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.measures.premium_measures import (
    POLICY_DIMS,
    earned_rolled,
    transactions_with_policies,
)
from actuarycanary.measures.premium_measures import (
    group_keys as premium_keys,
)
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.premium import CEDED_TYPE, PremiumError

PREMIUMS = "premiums"
POLICIES = "policies"
RI_COMMISSION = "RI_COMMISSION"
CLAIM_ONLY = ("origin_period", "valuation_date", "claim_size_class")


def _premium_side(
    inputs: MeasureInputs, request: MeasureRequest
) -> tuple[pl.DataFrame | None, list[str], str]:
    """Ceded over gross written premium; None and the reason when it cannot be shown."""
    if not (inputs.feeds[PREMIUMS]["type"] == CEDED_TYPE).any():
        return None, [], "premium ratio: no ceded premium in the premium file (CV03)"
    wanted = MeasureRequest(
        tuple(d for d in request.breakdowns if d in (*POLICY_DIMS, "calendar_period", "currency")),
        request.period,
        request.basis,
    )
    try:
        rows, notes = transactions_with_policies(inputs, wanted, ReinsuranceBasis.NET)
    except PremiumError as error:
        return None, [], f"premium ratio: {error}"
    keys = premium_keys(wanted)
    ceded = pl.col("type") == CEDED_TYPE
    frame = group_agg(
        rows,
        keys,
        [
            # the NET basis signs ceded premium as a deduction; the measure shows its size
            (pl.lit(0.0) - pl.col("amount").filter(ceded).sum()).alias("numerator"),
            pl.col("amount").filter(~ceded).sum().alias("denominator"),
            pl.col("_ref").unique().sort().alias("refs_premiums"),
        ],
    ).with_columns(
        pl.when(pl.col("denominator") > 0)
        .then(pl.col("numerator") / pl.col("denominator"))
        .alias(VALUE),
        note_when(pl.col("denominator") <= 0, "gross written premium is zero: not computed").alias(
            NOTE
        ),
        pl.lit("premium").alias("side"),
    )
    return frame, notes, ""


def _claims_side(
    inputs: MeasureInputs, request: MeasureRequest
) -> tuple[pl.DataFrame | None, list[str], str]:
    wanted = MeasureRequest(
        tuple(d for d in request.breakdowns if d not in ("calendar_period", "channel")),
        request.period,
        request.basis,
    )
    keys = claim_keys(wanted)
    try:
        ceded, notes = amounts_at(
            inputs,
            Basis(ReinsuranceBasis.CEDED, request.basis.currency),
            "incurred",
            [inputs.cut_off],
        )
        gross, _ = amounts_at(
            inputs,
            Basis(ReinsuranceBasis.GROSS, request.basis.currency),
            "incurred",
            [inputs.cut_off],
        )
    except BasisUnavailableError as error:
        return None, [], f"claims ratio: {error}"
    ceded, left = left_out(ceded, "incurred")
    gross, _ = left_out(gross, "incurred")
    ceded, dim_notes = prepared(ceded, inputs, wanted)
    gross, _ = prepared(gross, inputs, wanted)
    top = group_agg(ceded, keys, [pl.col(VALUE).sum(), refs(CONCEPT)])
    bottom = group_agg(gross, keys, [pl.col(VALUE).sum()])
    frame = ratio_frame(top, bottom, keys, (f"refs_{CONCEPT}",)).with_columns(
        note_when(pl.col("denominator") <= 0, "gross incurred is zero: not computed").alias(NOTE),
        pl.lit("claims").alias("side"),
    )
    return frame, [*notes, *left, *dim_notes, *origin_notes(inputs, wanted)], ""


def cession_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RI01: ceded over gross, for premium (by calendar period) and for claims (by origin)."""
    wants_claims = any(d in request.breakdowns for d in CLAIM_ONLY)
    wants_premium = "calendar_period" in request.breakdowns
    both = not wants_claims and not wants_premium
    parts: list[pl.DataFrame] = []
    notes: list[str] = []
    skipped: list[str] = []
    concepts: list[str] = []
    if wants_premium or both:
        frame, side_notes, why = _premium_side(inputs, request)
        if frame is not None:
            parts.append(frame)
            notes += side_notes
            concepts += [PREMIUMS]
        else:
            skipped.append(why)
    if wants_claims or both:
        frame, side_notes, why = _claims_side(inputs, request)
        if frame is not None:
            parts.append(frame)
            notes += side_notes
            concepts.append(CONCEPT)
        else:
            skipped.append(why)
    if not parts:
        return Missing("; ".join(skipped))
    keys = ["side", *dict.fromkeys(d for p in parts for d in p.columns if d in request.breakdowns)]
    frame = pl.concat(parts, how="diagonal_relaxed")
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True),
        tuple([*notes, *skipped]),
        tuple(concepts),
    )


def reinsurance_result(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RI02: change in ceded incurred plus reinsurance commission earned minus ceded premium
    earned, per calendar period."""
    if not (inputs.feeds[PREMIUMS]["type"] == CEDED_TYPE).any():
        return Missing("no ceded premium in the premium file (CV03)")
    keys = premium_keys(request)
    ceded_basis = Basis(ReinsuranceBasis.CEDED, request.basis.currency, request.basis.value)
    claim_request = MeasureRequest(
        tuple(
            d for d in request.breakdowns if d in ("segment", "line", "entity", "calendar_period")
        ),
        request.period,
        ceded_basis,
    )
    try:
        claims = incurred(spec, inputs, claim_request)
    except BasisUnavailableError as error:
        return Missing(str(error))
    if isinstance(claims, Missing):
        return claims
    premium_request = MeasureRequest(request.breakdowns, request.period, ceded_basis)
    try:
        ceded_premium, notes = earned_rolled(inputs, premium_request)
        has_commission = (inputs.feeds[PREMIUMS]["type"] == RI_COMMISSION).any()
        commission, more = (
            earned_rolled(
                inputs,
                MeasureRequest(request.breakdowns, request.period, request.basis),
                transaction_types=(RI_COMMISSION,),
            )
            if has_commission
            else (ceded_premium.head(0), [])
        )
    except PremiumError as error:
        return Missing(str(error))
    on = [k for k in keys if k in claims.frame.columns]
    claim_part = claims.frame.select(
        *on, pl.col(VALUE).alias("ceded_incurred_change"), f"refs_{CONCEPT}"
    )
    premium_part = ceded_premium.select(
        *keys, pl.col(VALUE).alias("ceded_premium_earned"), "refs_premiums"
    )
    commission_part = commission.select(*keys, pl.col(VALUE).alias("ri_commission_earned"))
    frame = (
        (
            claim_part.join(premium_part, on=on, how="full", coalesce=True)
            .join(commission_part, on=keys, how="left")
            .with_columns(
                pl.col("ceded_incurred_change").fill_null(0.0),
                pl.col("ceded_premium_earned").fill_null(0.0),
                pl.col("ri_commission_earned").fill_null(0.0),
            )
        )
        if on
        else None
    )
    if frame is None:
        return Missing("the result needs a breakdown that claims and premium share")
    frame = frame.with_columns(
        (
            pl.col("ceded_incurred_change")
            + pl.col("ri_commission_earned")
            - pl.col("ceded_premium_earned")
        ).alias(VALUE)
    ).with_columns(
        pl.when(pl.col("ceded_premium_earned") > 0)
        .then(pl.col(VALUE) / pl.col("ceded_premium_earned"))
        .alias("share_of_ceded_premium"),
    )
    if not has_commission:
        notes = [*notes, "no RI_COMMISSION rows: commission counts as zero"]
    return Computed(
        keep_columns(frame, keys).sort(keys, nulls_last=True),
        tuple([*claims.notes, *notes, *more]),
        (CONCEPT, PREMIUMS, POLICIES),
    )
