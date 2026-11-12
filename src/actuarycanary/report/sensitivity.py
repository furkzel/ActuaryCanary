"""Sensitivity of the reserve to its main assumptions, computed inside the run (record 0343).

Each variant reruns the methods of the run with one assumption changed and everything else as
the run had it, and compares the result with the run's own:

- development factors: every selected factor of both triangles moved to 1 + (f - 1)(1 +/- s),
  entered as MT02 `selected_factor` register entries; the selected IBNR (MT10, RS02);
- tail: the MT02 tail factor of every triangle raised by a fixed step, and the tail of the
  curve MT14 fitted (MT14 `selected_curve`, the curve the run's register chose); the selected
  IBNR;
- thin factors: the factors the rule of record 0776 set to 1.000 (a column resting on one link
  ratio) put back to the average, entered as MT02 `selected_factor` register entries; the
  selected unpaid (MT10, RS02), the unpaid being what the rule moves;
- future inflation: the MT07 unpaid at the run's future inflation (none means value-date
  prices, that is 0) moved by +/- one step; MT07 itself re-inflates the same future payments;
- discount curve: the present value of the expected unpaid (RS04) with the continuously
  compounded zero rates of the curve moved in parallel by +/- a step, D'(t) = D(t) e^(-d t).

The tier B methods are left out of the reruns: none of them feeds the selection (MT10) or
MT07, and leaving them out keeps the reruns to the chain ladder, Bornhuetter-Ferguson, Cape
Cod, the expected loss ratio, Mack and MT07. The variants and their steps are in the settings
of the run (`report.sensitivity`), so a change of a step changes the run id.
"""

from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister, column_label
from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.methods.inflation_adjusted import InflationAdjusted
from actuarycanary.methods.tail import CurveFit, TailFit
from actuarycanary.modules.reserving import GroupReserving, ReservingResult, run_reserving
from actuarycanary.modules.uncertainty import DISCOUNTED, UncertaintyResult
from actuarycanary.structures.triangles import MEASURES

SENSITIVITY_NAME = "sensitivity.csv"
FACTOR_STEP = 0.10  # (f - 1) scaled by 1 +/- this
TAIL_STEP = 0.01  # added to the tail factor
INFLATION_STEP = 0.01  # one point of future inflation
CURVE_STEP = 0.01  # 100 basis points on the continuously compounded zero rates
WHO = "sensitivity"
WHY = "sensitivity variant of the report (record 0343), never a judgement of the run"

IBNR = "selected IBNR (MT10, RS02)"
UNPAID = "selected unpaid (MT10, RS02)"
UNPAID_MT07 = "unpaid, nominal (MT07)"
PRESENT_VALUE = "present value of the expected unpaid (RS04)"

COLUMNS = (
    "segment", "line", "variant", "assumption", "change", "quantity", "value_basis", "base",
    "value", "difference", "relative", "note",
)  # fmt: skip
TEXT = ("segment", "line", "variant", "assumption", "change", "quantity", "value_basis", "note")


def settings() -> dict[str, Any]:
    """The variants of the sensitivity tables; part of the settings and the run id."""
    return {
        "factor_step": FACTOR_STEP,
        "tail_step": TAIL_STEP,
        "inflation_step": INFLATION_STEP,
        "curve_step": CURVE_STEP,
    }


@dataclass(frozen=True)
class Variant:
    name: str
    assumption: str
    change: str


VARIANTS = (
    Variant("factors_up", "development factors", f"(f − 1) × {1 + FACTOR_STEP:.2f}"),
    Variant("factors_down", "development factors", f"(f − 1) × {1 - FACTOR_STEP:.2f}"),
    Variant("tail_up", "tail factor", f"+ {TAIL_STEP:.2f}"),
    Variant("tail_fitted", "tail factor", "curve fitted by MT14"),
    Variant("thin_average", "thin development factors", "average instead of 1.000"),
    Variant("inflation_up", "future inflation", f"+ {INFLATION_STEP * 100:.0f} point"),
    Variant("inflation_down", "future inflation", f"− {INFLATION_STEP * 100:.0f} point"),
    Variant("curve_up", "discount curve", f"+ {CURVE_STEP * 10000:.0f} basis points"),
    Variant("curve_down", "discount curve", f"− {CURVE_STEP * 10000:.0f} basis points"),
)
BY_NAME = {v.name: v for v in VARIANTS}


def _scope(group: GroupReserving, measure: str) -> str:
    return "/".join((*group.group, measure))


def _without(
    register: AssumptionsRegister, method: str, name: str, scopes: set[str]
) -> list[Assumption]:
    return [
        e
        for e in register.entries
        if not (e.method == method and e.name == name and e.scope in scopes)
    ]


def _entry(method: str, name: str, scope: str, target: str, value: float | str) -> Assumption:
    return Assumption(
        method=method, name=name, scope=scope, target=target, value=value, who=WHO, why=WHY
    )


def factor_register(
    result: ReservingResult, register: AssumptionsRegister, step: float
) -> AssumptionsRegister:
    """The run's register with every selected factor f moved to 1 + (f - 1)(1 + step)."""
    added: list[Assumption] = []
    scopes: set[str] = set()
    for group in result.groups:
        for measure in MEASURES:
            chain = group.chain_ladder.get(measure)
            if not isinstance(chain, ChainLadder):
                continue
            scope = _scope(group, measure)
            scopes.add(scope)
            ages = group.triangles[measure].ages
            for j, factor in enumerate(chain.factors):
                if not np.isfinite(factor):
                    continue
                moved = 1.0 + (float(factor) - 1.0) * (1.0 + step)
                added.append(_entry("MT02", "selected_factor", scope, column_label(ages, j), moved))
    kept = _without(register, "MT02", "selected_factor", scopes)
    return AssumptionsRegister(entries=(*kept, *added))


def tail_register(
    result: ReservingResult, register: AssumptionsRegister, step: float
) -> AssumptionsRegister:
    """The run's register with the tail factor of every triangle raised by `step`."""
    added: list[Assumption] = []
    scopes: set[str] = set()
    for group in result.groups:
        for measure in MEASURES:
            chain = group.chain_ladder.get(measure)
            if not isinstance(chain, ChainLadder):
                continue
            scope = _scope(group, measure)
            if register.find("MT14", "selected_curve", scope).get(""):
                continue  # the tail is the fitted one; raising it is the fitted variant's job
            scopes.add(scope)
            added.append(_entry("MT02", "tail_factor", scope, "", chain.tail_factor + step))
    kept = _without(register, "MT02", "tail_factor", scopes)
    return AssumptionsRegister(entries=(*kept, *added))


def fitted_register(
    result: ReservingResult, register: AssumptionsRegister
) -> tuple[AssumptionsRegister, set[tuple[str, ...]]]:
    """The run's register with the curve MT14 chose selected on every triangle it fitted and
    whose tail no register entry sets; the groups where at least one triangle changed."""
    added: list[Assumption] = []
    changed: set[tuple[str, ...]] = set()
    for group in result.groups:
        tails = group.tier_b.tails if group.tier_b is not None else {}
        for measure in MEASURES:
            fit = tails.get(measure)
            scope = _scope(group, measure)
            if not isinstance(fit, TailFit) or not isinstance(fit.fits.get(fit.curve), CurveFit):
                continue
            if register.find("MT02", "tail_factor", scope).get(""):
                continue
            if register.find("MT14", "selected_curve", scope).get(""):
                continue  # the run already uses the fitted tail
            added.append(_entry("MT14", "selected_curve", scope, "", fit.curve.value))
            changed.add(group.group)
    return AssumptionsRegister(entries=(*register.entries, *added)), changed


def selected_ibnr(group: GroupReserving) -> float | None:
    ultimates = group.selected_ultimates()
    if not ultimates or any(u is None or not np.isfinite(u) for u in ultimates):
        return None
    incurred = group.triangles["incurred"].latest
    return float(np.nansum(np.array(ultimates, dtype=float)) - np.nansum(incurred))


def selected_unpaid(group: GroupReserving) -> float | None:
    ultimates = group.selected_ultimates()
    if not ultimates or any(u is None or not np.isfinite(u) for u in ultimates):
        return None
    paid = group.triangles["paid"].latest
    return float(np.nansum(np.array(ultimates, dtype=float)) - np.nansum(paid))


def thin_register(
    result: ReservingResult, register: AssumptionsRegister
) -> tuple[AssumptionsRegister, set[tuple[str, ...]]]:
    """The run's register with the average entered as the selected factor of every column the
    rule replaced; the groups that have such a column."""
    added: list[Assumption] = []
    changed: set[tuple[str, ...]] = set()
    for group in result.groups:
        for measure in MEASURES:
            chain = group.chain_ladder.get(measure)
            if not isinstance(chain, ChainLadder):
                continue
            ages = group.triangles[measure].ages
            for j in np.flatnonzero(chain.replaced):
                scope = _scope(group, measure)
                added.append(
                    _entry("MT02", "selected_factor", scope, column_label(ages, int(j)),
                           float(chain.averages[j]))
                )  # fmt: skip
                changed.add(group.group)
    return AssumptionsRegister(entries=(*register.entries, *added)), changed


def rerun(result: ReservingResult, register: AssumptionsRegister) -> ReservingResult:
    inputs = replace(result.inputs, register=register, tier_b=None)
    return run_reserving(result.triangles, result.settings, inputs)


def _row(
    group: tuple[str, ...],
    variant: Variant,
    quantity: str,
    basis: str,
    base: float | None,
    value: float | None,
    note: str = "",
) -> dict[str, Any]:
    known = base is not None and value is not None
    difference = value - base if known else None  # type: ignore[operator]
    relative = difference / base if known and base else None  # type: ignore[operator]
    return {
        "segment": group[0],
        "line": group[1],
        "variant": variant.name,
        "assumption": variant.assumption,
        "change": variant.change,
        "quantity": quantity,
        "value_basis": basis,
        "base": base,
        "value": None if value is None else value,
        "difference": difference,
        "relative": relative,
        "note": note,
    }


def _mt07_unpaid(result: InflationAdjusted, rate: float) -> float:
    found = replace(result, future_inflation=rate).nominal_future
    assert found is not None
    return float(np.nansum(found))


def present_values(cash_flows: pl.DataFrame, shift: float) -> dict[tuple[str, str], float]:
    """RS04 per line with the zero rates moved by `shift`: the expected nominal cash flows
    discounted with D(t) e^(-shift t), t the years from the discount date (0 before it)."""
    if not cash_flows.height:
        return {}
    years = cash_flows["years"].fill_null(0.0).to_numpy().clip(min=0.0)
    factors = cash_flows["discount_factor"].to_numpy() * np.exp(-shift * years)
    present = cash_flows["expected_nominal"].fill_null(0.0).to_numpy() * factors
    frame = cash_flows.select("segment", "line").with_columns(pl.Series("pv", present))
    return {
        (s, line): float(v)
        for s, line, v in frame.group_by("segment", "line").agg(pl.col("pv").sum()).iter_rows()
    }


def run_sensitivity(
    result: ReservingResult,
    register: AssumptionsRegister,
    uncertainty: UncertaintyResult | str,
) -> pl.DataFrame:
    """Every variant on every line, as rows of `sensitivity.csv`; a variant that cannot be
    computed on a line has one row with the reason in `note`."""
    rows: list[dict[str, Any]] = []
    # the run's own selection is the base: a rerun with the run's register gives it (tested)
    base = {g.group: selected_ibnr(g) for g in result.groups}
    reruns = {
        "factors_up": rerun(result, factor_register(result, register, FACTOR_STEP)),
        "factors_down": rerun(result, factor_register(result, register, -FACTOR_STEP)),
        "tail_up": rerun(result, tail_register(result, register, TAIL_STEP)),
    }
    fitted, changed = fitted_register(result, register)
    reruns["tail_fitted"] = rerun(result, fitted)
    thin, thin_groups = thin_register(result, register)
    base_unpaid = {g.group: selected_unpaid(g) for g in result.groups}
    if thin_groups:
        found_thin = rerun(result, thin)
        by_unpaid = {g.group: selected_unpaid(g) for g in found_thin.groups}
    for group in result.groups:
        variant = BY_NAME["thin_average"]
        before = base_unpaid.get(group.group)
        if group.group not in thin_groups:
            why = "the rule replaced no development factor on this line"
            rows.append(_row(group.group, variant, UNPAID, "NOMINAL", before, None, why))
            continue
        after = by_unpaid.get(group.group)
        note = "" if before is not None and after is not None else "no selected ultimate"
        rows.append(_row(group.group, variant, UNPAID, "NOMINAL", before, after, note))
    for name, found in reruns.items():
        variant = BY_NAME[name]
        by_group = {g.group: selected_ibnr(g) for g in found.groups}
        for group in result.groups:
            before, after = base.get(group.group), by_group.get(group.group)
            if name == "tail_fitted" and group.group not in changed:
                why = "MT14 fitted no tail curve on this line, or a register entry sets its tail"
                rows.append(_row(group.group, variant, IBNR, "NOMINAL", before, None, why))
                continue
            note = "" if before is not None and after is not None else "no selected ultimate"
            rows.append(_row(group.group, variant, IBNR, "NOMINAL", before, after, note))

    for group in result.groups:
        adjusted = group.inflation_adjusted
        for name, sign in (("inflation_up", 1.0), ("inflation_down", -1.0)):
            variant = BY_NAME[name]
            if not isinstance(adjusted, InflationAdjusted):
                reason = getattr(adjusted, "reason", "MT07 did not run")
                rows.append(_row(group.group, variant, UNPAID_MT07, "NOMINAL", None, None, reason))
                continue
            rate = adjusted.future_inflation or 0.0
            stated = (
                ""
                if adjusted.future_inflation is not None
                else ("no future inflation is stated: the base is at value-date prices (0)")
            )
            moved = _mt07_unpaid(adjusted, rate + sign * INFLATION_STEP)
            centre = _mt07_unpaid(adjusted, rate)
            rows.append(_row(group.group, variant, UNPAID_MT07, "NOMINAL", centre, moved, stated))

    available = isinstance(uncertainty, UncertaintyResult) and uncertainty.discount.available
    flows = uncertainty.cash_flows if isinstance(uncertainty, UncertaintyResult) else None
    centre = present_values(flows, 0.0) if available and flows is not None else {}
    for name, sign in (("curve_up", 1.0), ("curve_down", -1.0)):
        variant = BY_NAME[name]
        moved = present_values(flows, sign * CURVE_STEP) if available and flows is not None else {}
        for group in result.groups:
            key = (group.group[0], group.group[1])
            if not available:
                reason = (
                    uncertainty.discount.reason
                    if isinstance(uncertainty, UncertaintyResult)
                    else uncertainty
                )
                rows.append(_row(group.group, variant, PRESENT_VALUE, DISCOUNTED, None, None,
                                 f"no discounted figures: {reason}"))  # fmt: skip
                continue
            if key not in centre:
                rows.append(_row(group.group, variant, PRESENT_VALUE, DISCOUNTED, None, None,
                                 "no expected cash flows for this line (M12)"))  # fmt: skip
                continue
            rows.append(
                _row(group.group, variant, PRESENT_VALUE, DISCOUNTED, centre[key], moved[key])
            )
    schema = {c: (pl.String if c in TEXT else pl.Float64) for c in COLUMNS}
    return pl.DataFrame(rows, schema=schema, infer_schema_length=None)


__all__ = [
    "SENSITIVITY_NAME",
    "VARIANTS",
    "present_values",
    "rerun",
    "run_sensitivity",
    "selected_ibnr",
    "selected_unpaid",
    "settings",
]
