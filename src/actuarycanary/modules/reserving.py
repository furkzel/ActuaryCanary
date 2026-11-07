"""Reserving module (M04): the tier A methods per segment and line on the chosen basis.

Per group and per paid and incurred triangle: chain ladder (MT02), Bornhuetter–Ferguson
(MT03), Cape Cod (MT04), expected loss ratio (MT05) and the Mack standard error (MT06); on the
paid triangle also the inflation-adjusted chain ladder (MT07); on the incurred triangle the
selection (MT10). When the run gives the tier B inputs (`MethodInputs.tier_b`), the tier B
methods run beside them (record 0620): MT11 to MT16 and MT22, with the fitted tail of MT14 on
each chain ladder. Every judgement goes through the assumptions register (record 0037) and
comes back as the entries in force. Methods that cannot run keep their reason (record 0055).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson, bornhuetter_ferguson
from actuarycanary.methods.cape_cod import CapeCod, cape_cod
from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped
from actuarycanary.methods.diagnostics import (
    ChainLadderDiagnostics,
    Diagnostic,
    chain_ladder_diagnostics,
    negative_ibnr,
    thin_evidence,
)
from actuarycanary.methods.expected_loss_ratio import ExpectedLossRatio, expected_loss_ratio
from actuarycanary.methods.inflation_adjusted import (
    InflationAdjusted,
    inflation_adjusted_chain_ladder,
)
from actuarycanary.methods.judgement import (
    future_inflation,
    prior_loss_ratios,
    selection_overrides,
)
from actuarycanary.methods.judgement_tier_b import chain_ladder_with_tail
from actuarycanary.methods.mack import Mack, mack
from actuarycanary.methods.selection import Selection as UltimateSelection
from actuarycanary.methods.selection import select_ultimates
from actuarycanary.methods.tail import TailFit
from actuarycanary.modules.reserving_tier_b import TierBGroup, run_tier_b
from actuarycanary.modules.tier_b_inputs import TierBInputs
from actuarycanary.structures.triangles import MEASURES, Triangle, TriangleSet

SELECTION_MEASURE = "incurred"  # MT10 parameter `measure`, its default
INFLATION_MEASURE = "paid"  # MT07 runs on paid claims
UNDERWRITING_PREMIUM = (
    "earned premium by underwriting period is not built: premium is matched to accident periods"
)

Result = ChainLadder | Skipped


class ChainLadderSettings(BaseModel):
    """MT02 parameters; exclusions and factor overrides come from the assumptions register."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    average: Average = Average.VOLUME_WEIGHTED
    n_diagonals: int | None = Field(default=None, ge=1)
    exclude_high_low: bool = False
    tail_factor: float = Field(default=1.0, gt=0)
    min_origins: int = Field(default=3, ge=2)


@dataclass(frozen=True)
class MethodInputs:
    """What the methods need besides the run's own triangles."""

    register: AssumptionsRegister = field(default_factory=AssumptionsRegister)
    # earned premium (PR02) with segment, line, origin_period and earned_premium; None: not
    # available, and `premium_reason` says why
    premium: pl.DataFrame | None = None
    premium_reason: str = "no premiums and policies were loaded"
    # the same claims on the inflation-adjusted (MT07) and the nominal basis, paid only
    adjusted: TriangleSet | None = None
    nominal: TriangleSet | None = None
    adjusted_reason: str = "no market data with a price index was loaded"
    origin_axis: str = "accident"
    # the extra inputs and the seed of the tier B methods; None: they do not run (record 0620)
    tier_b: TierBInputs | None = None


@dataclass(frozen=True)
class OriginEstimate:
    """RS02 per origin and method: ultimate, unpaid (U - paid) and IBNR (U - incurred)."""

    origin: str
    paid: float
    incurred: float
    ultimate: dict[str, float | None]  # per method: "paid", "incurred"

    def unpaid(self, method: str) -> float | None:
        ultimate = self.ultimate[method]
        return None if ultimate is None else ultimate - self.paid

    def ibnr(self, method: str) -> float | None:
        ultimate = self.ultimate[method]
        return None if ultimate is None else ultimate - self.incurred


@dataclass(frozen=True)
class MeasureDiagnostic:
    """A diagnostic of the methods with the triangle it belongs to ("" for the whole group)."""

    measure: str
    item: Diagnostic


@dataclass(frozen=True)
class GroupReserving:
    group: tuple[str, ...]
    triangles: dict[str, Triangle]  # by measure
    chain_ladder: dict[str, Result]  # by measure of the triangle it ran on
    mack: dict[str, Mack | Skipped] = field(default_factory=dict)
    cape_cod: dict[str, CapeCod | Skipped] = field(default_factory=dict)
    bornhuetter_ferguson: dict[str, BornhuetterFerguson | Skipped] = field(default_factory=dict)
    expected_loss_ratio: dict[str, ExpectedLossRatio | Skipped] = field(default_factory=dict)
    inflation_adjusted: InflationAdjusted | Skipped | None = None
    inflation_adjusted_origins: tuple[str, ...] = ()
    selection: UltimateSelection | Skipped | None = None
    premium: np.ndarray | None = None
    chain_diagnostics: dict[str, ChainLadderDiagnostics] = field(default_factory=dict)
    diagnostics: tuple[MeasureDiagnostic, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    tier_b: TierBGroup | None = None

    def estimates(self) -> list[OriginEstimate]:
        paid, incurred = self.triangles["paid"].latest, self.triangles["incurred"].latest
        rows: list[OriginEstimate] = []
        for i, origin in enumerate(self.triangles["paid"].origins):
            ultimate: dict[str, float | None] = {}
            for measure, result in self.chain_ladder.items():
                ultimate[measure] = (
                    float(result.ultimate[i]) if isinstance(result, ChainLadder) else None
                )
            rows.append(OriginEstimate(origin, float(paid[i]), float(incurred[i]), ultimate))
        return rows

    def totals(self) -> OriginEstimate:
        rows = self.estimates()
        ultimate: dict[str, float | None] = {}
        for measure in self.chain_ladder:
            known = [v for r in rows if (v := r.ultimate[measure]) is not None]
            ultimate[measure] = float(sum(known)) if len(known) == len(rows) else None
        return OriginEstimate(
            "Total",
            float(sum(r.paid for r in rows)),
            float(sum(r.incurred for r in rows)),
            ultimate,
        )

    def selected_ultimates(self) -> list[float | None]:
        """The MT10 ultimate per origin, None where there is no selection."""
        if not isinstance(self.selection, UltimateSelection):
            return [None] * len(self.triangles["paid"].origins)
        return [float(u) for u in self.selection.ultimate]

    def method_ultimates(self, measure: str) -> dict[str, np.ndarray]:
        """Ultimate per origin of each method that ran on the triangle `measure` (NaN where an
        origin was not run)."""
        found: dict[str, np.ndarray] = {}
        chain = self.chain_ladder.get(measure)
        if isinstance(chain, ChainLadder):
            found["chain_ladder"] = chain.ultimate
        for name, results in (
            ("bornhuetter_ferguson", self.bornhuetter_ferguson),
            ("cape_cod", self.cape_cod),
            ("expected_loss_ratio", self.expected_loss_ratio),
        ):
            result = results.get(measure)
            if result is not None and not isinstance(result, Skipped):
                found[name] = result.ultimate
        return found


@dataclass(frozen=True)
class ReservingResult:
    triangles: TriangleSet
    settings: ChainLadderSettings
    groups: tuple[GroupReserving, ...]
    inputs: MethodInputs = field(default_factory=MethodInputs)
    # the entries in force of methods outside the triangles (MT17, MT18), added by the run
    extra_assumptions: tuple[Assumption, ...] = ()

    def assumptions(self) -> list[Assumption]:
        """Every judgement in force: the register's entries and the defaults the methods used."""
        return [a for g in self.groups for a in g.assumptions] + list(self.extra_assumptions)

    def diagnostics_by_group(self) -> dict[tuple[str, ...], int]:
        return {g.group: len(g.diagnostics) for g in self.groups}


@dataclass(frozen=True)
class _Context:
    cut_off: date
    development_months: int
    origin_months: int
    # at an earlier valuation the earned premium of an origin still open is not known
    mask_open_origins: bool
    full: bool  # Mack, inflation-adjusted chain ladder and diagnostics, not only the selection
    adjusted: dict[tuple[str, ...], Triangle]
    nominal: dict[tuple[str, ...], Triangle]
    value_date: date | None


def truncate_triangle(triangle: Triangle, valuation_point: date) -> Triangle | None:
    """The triangle as known at an earlier valuation point of its grid: the cells valued on or
    before it, without the origins that had not started (None when it is not on the grid)."""
    if valuation_point not in triangle.valuation_points:
        return None
    column = triangle.valuation_points.index(valuation_point)
    keep = triangle.observed & (triangle.calendar <= column)
    if not keep.any():
        return None
    rows, columns = keep.any(axis=1), keep.any(axis=0)

    def cut(array: np.ndarray) -> np.ndarray:
        return array[rows][:, columns]

    return replace(
        triangle,
        origins=tuple(o for o, k in zip(triangle.origins, rows, strict=True) if k),
        ages=tuple(a for a, k in zip(triangle.ages, columns, strict=True) if k),
        cumulative=cut(np.where(keep, triangle.cumulative, np.nan)),
        claim_counts=cut(np.where(keep, triangle.claim_counts, -1)),
        calendar=cut(np.where(keep, triangle.calendar, -1)),
        valuation_points=triangle.valuation_points[: column + 1],
    )


def _premium_lookup(frame: pl.DataFrame | None) -> dict[tuple[str, str], dict[str, float]]:
    if frame is None:
        return {}
    lookup: dict[tuple[str, str], dict[str, float]] = {}
    for segment, line, origin, amount in frame.select(
        "segment", "line", "origin_period", "earned_premium"
    ).iter_rows():
        if amount is not None:
            lookup.setdefault((segment, line), {})[origin] = float(amount)
    return lookup


def _group_premium(
    triangle: Triangle,
    lookup: Mapping[tuple[str, str], Mapping[str, float]],
    context: _Context,
) -> np.ndarray:
    """Earned premium per origin of `triangle`, NaN where there is none or it is not final."""
    found = lookup.get((triangle.group[0], triangle.group[1]), {})
    premium = np.array([found.get(o, np.nan) for o in triangle.origins], dtype=float)
    if context.mask_open_origins:
        latest_age = np.array([triangle.ages[j] for j in triangle.latest_index])
        premium[latest_age < context.origin_months] = np.nan
    return premium


def reserve_group(
    group: tuple[str, ...],
    triangles: dict[str, Triangle],
    settings: ChainLadderSettings,
    inputs: MethodInputs,
    lookup: Mapping[tuple[str, str], Mapping[str, float]],
    context: _Context,
) -> GroupReserving:
    register = inputs.register
    axis = inputs.origin_axis
    entries: list[Assumption] = []
    chains: dict[str, Result] = {}
    macks: dict[str, Mack | Skipped] = {}
    capes: dict[str, CapeCod | Skipped] = {}
    fergusons: dict[str, BornhuetterFerguson | Skipped] = {}
    ratios: dict[str, ExpectedLossRatio | Skipped] = {}
    chain_diagnostics: dict[str, ChainLadderDiagnostics] = {}
    tails: dict[str, TailFit | Skipped | None] = {}
    diagnostics: list[MeasureDiagnostic] = []
    premium = (
        _group_premium(triangles["incurred"], lookup, context)
        if inputs.premium is not None
        else None
    )
    if axis == "underwriting":
        premium = None
    premium_reason = UNDERWRITING_PREMIUM if axis == "underwriting" else inputs.premium_reason

    for measure in MEASURES:
        t = triangles[measure]
        scope = "/".join((*group, measure))
        chain, tails[measure], used = chain_ladder_with_tail(
            t.cumulative,
            origins=t.origins,
            ages=t.ages,
            scope=scope,
            register=register,
            calendar=t.calendar,
            average=settings.average,
            n_diagonals=settings.n_diagonals,
            exclude_high_low=settings.exclude_high_low,
            tail_factor=settings.tail_factor,
            min_origins=settings.min_origins,
        )
        chains[measure] = chain
        entries += used
        if premium is None:
            capes[measure] = Skipped("MT04", premium_reason)
            fergusons[measure] = Skipped("MT03", premium_reason)
            ratios[measure] = Skipped("MT05", premium_reason)
        elif isinstance(chain, Skipped):
            capes[measure] = Skipped("MT04", chain.reason)
            fergusons[measure] = Skipped("MT03", chain.reason)
            ratios[measure] = Skipped("MT05", chain.reason)
        else:
            cape = cape_cod(chain, premium, origin_axis=axis)
            capes[measure] = cape
            prior = cape.expected_loss_ratio if isinstance(cape, CapeCod) else None
            bf_ratio, bf_source, used = prior_loss_ratios(
                "MT03", "prior_loss_ratio", t.origins, scope, register, prior
            )
            entries += used
            fergusons[measure] = bornhuetter_ferguson(
                chain, premium, bf_ratio, prior_source=bf_source, origin_axis=axis
            )
            elr_ratio, elr_source, used = prior_loss_ratios(
                "MT05", "expected_loss_ratio", t.origins, scope, register, prior
            )
            entries += used
            ratios[measure] = expected_loss_ratio(
                premium,
                elr_ratio,
                triangles["incurred"].latest,
                source=elr_source,
                origin_axis=axis,
            )
        if context.full:
            macks[measure] = mack(
                t.cumulative, calendar=t.calendar, min_origins=settings.min_origins
            )
            if isinstance(chain, ChainLadder):
                found = chain_ladder_diagnostics(chain, t.cumulative, t.origins, t.ages, t.calendar)
                chain_diagnostics[measure] = found
                diagnostics += [
                    MeasureDiagnostic(measure, w)
                    for w in found.warnings
                    if w.code != "THIN_EVIDENCE"  # said once for the group below
                ]

    paid_chain = chains["paid"]
    if context.full and isinstance(paid_chain, ChainLadder):
        diagnostics += [
            MeasureDiagnostic("paid", d)
            for d in negative_ibnr(
                "MT02", paid_chain.ultimate, triangles["incurred"].latest, triangles["paid"].origins
            )
        ]

    selected_scope = "/".join((*group, SELECTION_MEASURE))
    overrides, threshold, used = selection_overrides(
        triangles[SELECTION_MEASURE].origins, selected_scope, register
    )
    entries += used
    selection = select_ultimates(
        chains[SELECTION_MEASURE],
        fergusons[SELECTION_MEASURE],
        bf_below_maturity=threshold,
        overrides=overrides,
    )

    adjusted: InflationAdjusted | Skipped | None = None
    adjusted_origins: tuple[str, ...] = ()
    tier_b: TierBGroup | None = None
    if context.full:
        adjusted, adjusted_origins, used = _inflation_adjusted(
            group, chains[INFLATION_MEASURE], settings, inputs, context
        )
        entries += used
        if inputs.tier_b is not None:
            tier_b, used = run_tier_b(
                group,
                triangles,
                chains,
                fergusons,
                capes,
                tails,
                selection,
                premium,
                register,
                inputs.tier_b.source,
                inputs.tier_b.seed,
                context.development_months,
                SELECTION_MEASURE,
            )
            entries += used
            diagnostics += [MeasureDiagnostic(m, d) for m, d in tier_b.diagnostics]
        thin = thin_evidence(
            _methods_that_ran(chains, fergusons, capes, ratios, macks, adjusted, selection, tier_b),
            len(triangles["paid"].origins),
        )
        if thin:
            diagnostics.insert(0, MeasureDiagnostic("", thin))

    return GroupReserving(
        group,
        triangles,
        chains,
        macks,
        capes,
        fergusons,
        ratios,
        adjusted,
        adjusted_origins,
        selection,
        premium,
        chain_diagnostics,
        tuple(diagnostics),
        tuple(entries),
        tier_b,
    )


def _methods_that_ran(
    chains: Mapping[str, Result],
    fergusons: Mapping[str, BornhuetterFerguson | Skipped],
    capes: Mapping[str, CapeCod | Skipped],
    ratios: Mapping[str, ExpectedLossRatio | Skipped],
    macks: Mapping[str, Mack | Skipped],
    adjusted: InflationAdjusted | Skipped | None,
    selection: UltimateSelection | Skipped | None,
    tier_b: TierBGroup | None = None,
) -> str:
    ran: list[tuple[str, Iterable[object]]] = [
        ("MT02", chains.values()),
        ("MT03", fergusons.values()),
        ("MT04", capes.values()),
        ("MT05", ratios.values()),
        ("MT06", macks.values()),
        ("MT07", [adjusted]),
        ("MT10", [selection]),
    ]
    if tier_b is not None:
        by_method: dict[str, list[object]] = {}
        for method, outcome in tier_b.outcomes():
            by_method.setdefault(method, []).append(outcome)
        ran += sorted(by_method.items())
    return ", ".join(
        m for m, results in ran if any(r and not isinstance(r, Skipped) for r in results)
    )


def _inflation_adjusted(
    group: tuple[str, ...],
    paid_chain: Result,
    settings: ChainLadderSettings,
    inputs: MethodInputs,
    context: _Context,
) -> tuple[InflationAdjusted | Skipped, tuple[str, ...], list[Assumption]]:
    scope = "/".join((*group, INFLATION_MEASURE))
    inflation, entry = future_inflation(scope, inputs.register)
    adjusted = context.adjusted.get(group)
    nominal = context.nominal.get(group)
    if adjusted is None or nominal is None:
        reason = (
            inputs.adjusted_reason
            if not context.adjusted
            else ("the paid claims of this group are not in the inflation-adjusted triangles")
        )
        return Skipped("MT07", reason), (), [entry]
    tail = paid_chain.tail_factor if isinstance(paid_chain, ChainLadder) else settings.tail_factor
    paid_nominal = dict(zip(nominal.origins, nominal.latest, strict=True))
    nominal_paid = np.array([paid_nominal.get(o, np.nan) for o in adjusted.origins], dtype=float)
    same = (
        nominal.cumulative.shape == adjusted.cumulative.shape
        and nominal.origins == adjusted.origins
    )
    result = inflation_adjusted_chain_ladder(
        adjusted.cumulative,
        nominal_paid=nominal_paid,
        cut_off=context.cut_off,
        development_months=context.development_months,
        value_date=context.value_date,
        future_inflation=inflation,
        nominal=nominal.cumulative if same else None,
        calendar=adjusted.calendar,
        average=settings.average,
        n_diagonals=settings.n_diagonals,
        exclude_high_low=settings.exclude_high_low,
        tail_factor=tail,
        min_origins=settings.min_origins,
    )
    return result, adjusted.origins, [entry]


def run_reserving(
    triangles: TriangleSet,
    settings: ChainLadderSettings,
    inputs: MethodInputs | None = None,
    *,
    full: bool = True,
) -> ReservingResult:
    """The methods for every group of `triangles`. `full=False` runs only what the selection
    needs (chain ladder, Bornhuetter–Ferguson, Cape Cod, expected loss ratio and MT10)."""
    inputs = inputs or MethodInputs()
    lookup = _premium_lookup(inputs.premium)
    context = _Context(
        cut_off=triangles.cut_off,
        development_months=triangles.settings.development_period.months,
        origin_months=triangles.settings.origin_period.months,
        mask_open_origins=not full,
        full=full,
        adjusted=_by_group(inputs.adjusted),
        nominal=_by_group(inputs.nominal),
        value_date=inputs.adjusted.value_date if inputs.adjusted else None,
    )
    groups = [
        reserve_group(
            group, {m: triangles.get(m, group) for m in MEASURES}, settings, inputs, lookup, context
        )
        for group in triangles.groups
    ]
    return ReservingResult(triangles, settings, tuple(groups), inputs)


def _by_group(triangles: TriangleSet | None) -> dict[tuple[str, ...], Triangle]:
    if triangles is None:
        return {}
    return {t.group: t for t in triangles.triangles if t.measure == INFLATION_MEASURE}


METHOD_TITLES = {
    "MT02": "chain ladder",
    "MT03": "Bornhuetter–Ferguson",
    "MT04": "Cape Cod",
    "MT05": "expected loss ratio",
    "MT06": "Mack standard error",
    "MT07": "inflation-adjusted chain ladder",
    "MT10": "selection",
    "MT11": "bootstrap",
    "MT12": "Munich chain ladder",
    "MT13": "Benktander",
    "MT14": "tail factor fitting",
    "MT15": "separation",
    "MT16": "frequency–severity",
    "MT22": "back-test",
}
PER_GROUP = ("MT07", "MT10", "MT11", "MT12", "MT13", "MT15", "MT16", "MT22")  # else per triangle


def _outcomes(result: ReservingResult) -> list[tuple[str, object]]:
    """Every outcome of every method on every group and triangle, with the method ID."""
    found: list[tuple[str, object]] = []
    for group in result.groups:
        for method, outcomes in (
            ("MT02", group.chain_ladder),
            ("MT03", group.bornhuetter_ferguson),
            ("MT04", group.cape_cod),
            ("MT05", group.expected_loss_ratio),
            ("MT06", group.mack),
        ):
            found += [(method, outcome) for outcome in outcomes.values()]
        found += [("MT07", group.inflation_adjusted), ("MT10", group.selection)]
        if group.tier_b is not None:
            found += group.tier_b.outcomes()
    return found


def methods_run(result: ReservingResult) -> list[str]:
    """IDs of the methods that produced a result for at least one group (MT01 always)."""
    ran = {"MT01"} | {
        m for m, o in _outcomes(result) if o is not None and not isinstance(o, Skipped)
    }
    return sorted(ran)


def not_run_notes(result: ReservingResult) -> list[str]:
    """Why methods did not run, one line per method and reason with how many triangles (or
    groups) it concerns; origins left out of a method that did run are not listed here."""
    found: dict[tuple[str, str], int] = {}
    total: dict[str, int] = {}
    for method, outcome in _outcomes(result):
        total[method] = total.get(method, 0) + 1
        if isinstance(outcome, Skipped):
            key = (method, outcome.reason)
            found[key] = found.get(key, 0) + 1
    return [
        f"{method} {METHOD_TITLES[method]} did not run for {count} of {total[method]}"
        f" {'groups' if method in PER_GROUP else 'triangles'}: {reason}"
        for (method, reason), count in sorted(found.items())
    ]


def earlier_result(result: ReservingResult, valuation_date: date) -> ReservingResult | None:
    """The selection inputs as known at an earlier valuation of the development grid, with
    the settings and register of the run (AE01, selection_source recomputed); None when the
    date is not on the grid."""
    truncated = [truncate_triangle(t, valuation_date) for t in result.triangles.triangles]
    found = tuple(t for t in truncated if t is not None)
    if not found:
        return None
    earlier = replace(result.triangles, cut_off=valuation_date, triangles=found)
    return run_reserving(earlier, result.settings, result.inputs, full=False)


__all__ = [
    "ChainLadderSettings",
    "GroupReserving",
    "MeasureDiagnostic",
    "MethodInputs",
    "OriginEstimate",
    "ReservingResult",
    "earlier_result",
    "methods_run",
    "not_run_notes",
    "reserve_group",
    "run_reserving",
    "truncate_triangle",
]
