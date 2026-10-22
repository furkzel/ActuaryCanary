"""Measures built from other measures: RT01 loss ratio, RT02 combined ratio and AE01 actual
versus expected (blueprint 8.1, decision 0051). Method outputs come through the port only."""

from collections.abc import Sequence

import numpy as np
import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.measures.claim_amounts import (
    CONCEPT,
    earlier_valuation,
    incurred,
    origin_notes,
    paid,
)
from actuarycanary.measures.common import (
    group_agg,
    keep_columns,
    span_labels,
)
from actuarycanary.measures.expense_measures import commission_ratio, expense_ratio
from actuarycanary.measures.model import (
    NOTE,
    VALUE,
    Computed,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.measures.port import NotAvailable
from actuarycanary.measures.premium_measures import earned_rolled
from actuarycanary.measures.premium_measures import group_keys as premium_keys
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.premium import PremiumError

PREMIUMS = "premiums"
POLICIES = "policies"
CLAIM_LEVEL = ("segment", "line", "entity", "product", "partner")
VIEWS = ("incurred", "paid", "ultimate")


def _claim_request(request: MeasureRequest, drop: Sequence[str] = ()) -> MeasureRequest:
    dims = tuple(d for d in request.breakdowns if d not in drop)
    return MeasureRequest(dims, request.period, request.basis, params=request.params)


def loss_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RT01: paid, incurred and selected ultimate of an accident period over its earned premium;
    by calendar period, the incurred movement over the earned premium of the period."""
    dims = list(request.breakdowns)
    calendar = "calendar_period" in dims
    separated = [d for d in dims if d in CLAIM_LEVEL]
    if "channel" in dims:
        return Missing("claims carry no channel, so claims cannot be split by channel")
    if not inputs.has("claims") and (separated or "origin_period" in dims):
        return Missing(
            "claims are not loaded: the accident view and the segment and line breakdowns need "
            "them; only the all-business calendar view is shown, segments not separated"
        )
    keys = premium_keys(request)
    period_key = "calendar_period" if calendar else "origin_period"
    try:
        premium, notes = earned_rolled(
            inputs,
            MeasureRequest(
                tuple("calendar_period" if d == "origin_period" else d for d in request.breakdowns),
                request.period,
                request.basis,
            ),
        )
    except PremiumError as error:
        return Missing(str(error))
    premium = premium.rename({VALUE: "earned_premium"})
    if "calendar_period" in premium.columns and not calendar:
        premium = premium.rename({"calendar_period": "origin_period"})
    claim_request = _claim_request(request)
    if calendar:
        movement = incurred(spec, inputs, claim_request)
        if isinstance(movement, Missing):
            return movement
        claim_frame = movement.frame.rename({VALUE: "incurred"})
        notes += list(movement.notes)
    else:
        top = paid(spec, inputs, claim_request)
        bottom = incurred(spec, inputs, claim_request)
        if isinstance(top, Missing):
            return top
        if isinstance(bottom, Missing):
            return bottom
        claim_frame = (
            top.frame.rename({VALUE: "paid"}).join(
                bottom.frame.rename({VALUE: "incurred"}).drop(f"refs_{CONCEPT}"),
                on=[k for k in keys if k in top.frame.columns],
                how="full",
                coalesce=True,
            )
            if [k for k in keys if k in top.frame.columns]
            else pl.concat(
                [
                    top.frame.rename({VALUE: "paid"}),
                    bottom.frame.select(pl.col(VALUE).alias("incurred")),
                ],
                how="horizontal",
            )
        )
        notes += [*top.notes, *bottom.notes]
    on = [k for k in keys if k in claim_frame.columns and k in premium.columns]
    joined = (
        claim_frame.join(premium, on=on, how="full", coalesce=True)
        if on
        else pl.concat([claim_frame, premium], how="horizontal")
    )
    # a period outside the dates the claims cover has no claims data: it is missing, not zero
    claim_dates = (
        inputs.feeds["claims"]["occurrence_date"]
        if inputs.has("claims") and not calendar
        else inputs.feeds["claim_valuations"]["valuation_date"]
    )
    covered = span_labels(
        claim_dates.min(), claim_dates.max(), request.period, inputs.fiscal_year_start_month
    )
    if period_key in joined.columns:
        joined = joined.filter(pl.col(period_key).is_in(covered))
    for column in ("paid", "incurred"):
        if column not in joined.columns:
            joined = joined.with_columns(pl.lit(None, pl.Float64).alias(column))
    joined = joined.with_columns(
        pl.col("paid").fill_null(0.0) if not calendar else pl.col("paid"),
        pl.col("incurred").fill_null(0.0),
        pl.col("earned_premium").fill_null(0.0),
    )
    joined, ultimate_note = _with_ultimate(joined, inputs, keys, calendar, request.basis.label())
    if ultimate_note:
        notes.append(ultimate_note)
    positive = pl.col("earned_premium") > 0
    ratios = [
        pl.when(positive).then(pl.col(c) / pl.col("earned_premium")).alias(f"{c}_ratio")
        for c in ("paid", "incurred", "ultimate")
        if c in joined.columns
    ]
    frame = joined.with_columns(ratios)
    view = request.view if request.view in VIEWS else "incurred"
    if f"{view}_ratio" not in frame.columns:
        return Missing(f"the {view} ratio is not available: {ultimate_note or 'no values'}")
    frame = frame.with_columns(
        pl.col(f"{view}_ratio").alias(VALUE),
        pl.when(~positive)
        .then(pl.lit("earned premium is zero or negative: not computed"))
        .otherwise(pl.lit(""))
        .alias(NOTE),
    )
    if not calendar and period_key not in dims:
        notes.append("all periods together")
    if not separated and not inputs.has("claims"):
        notes.append("segments not separated")
    return Computed(
        keep_columns(frame, keys).sort([k for k in keys if k in frame.columns], nulls_last=True)
        if keys
        else frame,
        tuple(dict.fromkeys([*notes, *origin_notes(inputs, request)])),
        (CONCEPT, PREMIUMS, POLICIES),
    )


def _with_ultimate(
    frame: pl.DataFrame, inputs: MeasureInputs, keys: Sequence[str], calendar: bool, basis: str
) -> tuple[pl.DataFrame, str]:
    """Add the selected ultimate (MT10, through the port) to an accident-view frame."""
    if calendar:
        return frame, "the ultimate ratio exists in the accident view only"
    selection = inputs.methods.selection(inputs.cut_off, basis)
    if isinstance(selection, NotAvailable):
        return frame, f"ultimate ratio not available: {selection.reason}"
    values = pl.DataFrame(
        [(s, line, o, u) for (s, line, o), u in selection.ultimates.items()],
        schema={
            "segment": pl.String,
            "line": pl.String,
            "origin_period": pl.String,
            "ultimate": pl.Float64,
        },
        orient="row",
    )
    levels = [k for k in ("segment", "line", "origin_period") if k in keys]
    if levels and not set(levels) <= set(frame.columns):
        return frame, "ultimate ratio not available: the ultimate needs the same breakdowns"
    summed = group_agg(values, levels, [pl.col("ultimate").sum()])
    joined = (
        frame.join(summed, on=levels, how="left") if levels else frame.join(summed, how="cross")
    )
    return joined, ""


def combined_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RT02: ultimate loss ratio plus expense ratio plus commission ratio of an accident period."""
    if request.basis.reinsurance is not ReinsuranceBasis.GROSS:
        return Missing(
            "a net combined ratio needs net expense and commission definitions: not in 1.0"
        )
    keys = list(request.breakdowns)
    calendar_keys = tuple("calendar_period" if d == "origin_period" else d for d in keys)
    loss = loss_ratio(
        spec, inputs, MeasureRequest(tuple(keys), request.period, request.basis, "ultimate")
    )
    if isinstance(loss, Missing):
        return Missing(f"loss ratio: {loss.reason}")
    commission = commission_ratio(
        spec, inputs, MeasureRequest(calendar_keys, request.period, request.basis)
    )
    if isinstance(commission, Missing):
        return Missing(
            f"commission ratio not available ({commission.reason}); a combined ratio without "
            "commission would understate it"
        )
    expense = expense_ratio(
        spec, inputs, MeasureRequest(calendar_keys, request.period, request.basis)
    )
    if isinstance(expense, Missing):
        return Missing(f"expense ratio: {expense.reason}")
    on = [k for k in keys if k in loss.frame.columns]
    renamed = {"calendar_period": "origin_period"}
    commission_frame = (
        commission.frame.rename(
            {k: v for k, v in renamed.items() if k in commission.frame.columns}
        ).select(*on, pl.col(VALUE).alias("commission_ratio"))
        if on
        else commission.frame.select(pl.col(VALUE).alias("commission_ratio"))
    )
    expense_frame = (
        expense.frame.rename(
            {k: v for k, v in renamed.items() if k in expense.frame.columns}
        ).select(*on, pl.col(VALUE).alias("expense_ratio"))
        if on
        else expense.frame.select(pl.col(VALUE).alias("expense_ratio"))
    )
    frame = loss.frame.select(*on, pl.col("ultimate_ratio").alias("ultimate_loss_ratio"))
    frame = frame.join(expense_frame, on=on, how="left").join(commission_frame, on=on, how="left")
    frame = frame.with_columns(
        (
            pl.col("ultimate_loss_ratio") + pl.col("expense_ratio") + pl.col("commission_ratio")
        ).alias(VALUE),
        pl.when(pl.col("expense_ratio").is_null())
        .then(pl.lit("expenses are carried at a higher level than this: not computed"))
        .otherwise(pl.lit(""))
        .alias(NOTE),
    )
    return Computed(
        keep_columns(frame, keys).sort(on, nulls_last=True) if on else frame,
        tuple(dict.fromkeys([*loss.notes, *commission.notes, *expense.notes])),
        (CONCEPT, PREMIUMS, POLICIES, "expenses"),
    )


def actual_versus_expected(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """AE01: the movement of incurred (and paid) between two valuations over the movement the
    selection at the earlier valuation expected."""
    triangles = inputs.triangles
    if triangles is None:
        return Missing("no triangles were built (MT01)")
    v1 = inputs.cut_off
    v0 = earlier_valuation(inputs, request)
    selection = inputs.methods.selection(v0, request.basis.label())
    if isinstance(selection, NotAvailable):
        return Missing(f"the selection at {v0} is not available: {selection.reason}")
    points = triangles.triangles[0].valuation_points
    if v0 not in points:
        return Missing(f"{v0} is not on the development grid of {v1} (CV04)")
    column = points.index(v0)
    rows: list[dict[str, object]] = []
    for group in triangles.groups:
        for measure in ("incurred", "paid"):
            triangle = triangles.get(measure, group)
            curve = selection.cdfs.get((measure, group[0], group[1]))
            if curve is None:
                continue
            for i, origin in enumerate(triangle.origins):
                at_v0 = np.flatnonzero(triangle.calendar[i] == column)
                if not len(at_v0):
                    continue  # the origin had not started at v0
                j0, j1 = int(at_v0[0]), int(triangle.latest_index[i])
                a0, a1 = triangle.ages[j0], triangle.ages[j1]
                if (
                    a0 not in curve
                    or a1 not in curve
                    or (group[0], group[1], origin) not in selection.ultimates
                ):
                    continue
                key = (group[0], group[1], origin)
                prior = selection.expected.get(key, selection.ultimates[key])
                actual = float(triangle.cumulative[i, j1] - triangle.cumulative[i, j0])
                expected = prior * (1 / curve[a1] - 1 / curve[a0])
                rows.append(
                    {
                        "segment": group[0],
                        "line": group[1],
                        "origin_period": origin,
                        "measure": measure,
                        "numerator": actual,
                        "denominator": expected,
                    }
                )
    if not rows:
        return Missing("the selection holds no factors for the origins observed at both valuations")
    keys = [d for d in request.breakdowns if d in ("segment", "line", "origin_period")]
    frame = group_agg(
        pl.DataFrame(rows),
        [*keys, "measure"],
        [pl.col("numerator").sum(), pl.col("denominator").sum()],
    ).with_columns(
        pl.when(pl.col("denominator") != 0)
        .then(pl.col("numerator") / pl.col("denominator"))
        .alias(VALUE),
        (pl.col("numerator") - pl.col("denominator")).alias("difference"),
        pl.when(pl.col("denominator") == 0)
        .then(pl.lit("expected movement is zero: ratio not computed, difference shown"))
        .otherwise(pl.lit(""))
        .alias(NOTE),
    )
    return Computed(
        keep_columns(frame, [*keys, "measure"]).sort([*keys, "measure"]),
        (f"valuations {v0} and {v1}; total ratio is the sum of A over the sum of E",),
        (CONCEPT,),
    )
