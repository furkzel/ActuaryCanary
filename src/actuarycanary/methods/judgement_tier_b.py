"""Tier B judgements: from the assumptions register to method parameters, and back to the
entries in force (as `methods.judgement` does for tier A).

Every parameter of a tier B method that is a judgement has a row in PARAMETERS with its
default and what it allows. `parameters` reads the user's entries for one scope and returns the
parameters with one entry in force per parameter: the user's entry or the default with
who = "default". The fitted tail of MT14 replaces the MT02 tail only when the user selects a
curve (`chain_ladder_with_tail`).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.assumptions import (
    Assumption,
    AssumptionError,
    AssumptionsRegister,
    Value,
)
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.judgement import TAIL_DEFAULT, _entry, chain_ladder_judged
from actuarycanary.methods.tail import Curve, TailFit, fit_tail

ANY = None  # a number without a list of allowed values


@dataclass(frozen=True)
class Parameter:
    name: str
    default: Value
    allowed: tuple[str, ...] | None  # text choices; None for a number or a flag
    why: str
    minimum: float | None = None  # numbers: smallest allowed value
    whole: bool = False  # numbers: a whole number


PARAMETERS: dict[str, tuple[Parameter, ...]] = {
    "MT11": (
        Parameter("n_simulations", 10_000, ANY, "MT11 default: 10,000 bootstrap samples",
                  minimum=2, whole=True),
        Parameter("process_distribution", "gamma", ("gamma", "odp"),
                  "MT11 default: gamma process error (decision 0609)"),
        Parameter("scale", "constant", ("constant", "by_development"),
                  "MT11 default: one scale parameter for the triangle"),
        Parameter("centre_residuals", True, ANY,
                  "MT11 default: the residual pool is centred (decision 0612)"),
        Parameter("tail_factor", 1.0, ANY, "MT11 default: the tail of MT02", minimum=1.0),
    ),
    "MT12": (
        Parameter("sigma_extrapolation", "mack", ("mack",),
                  "MT12 default: last variance parameters extrapolated as in MT06"),
        Parameter("min_origins", 5, ANY, "MT12 default", minimum=2, whole=True),
    ),
    "MT13": (
        Parameter("blend", "benktander", ("benktander",), "MT13: Benktander only (0613)"),
        Parameter("iterations", 1, ANY, "MT13 default: the classical Benktander estimate",
                  minimum=0, whole=True),
        Parameter("prior", "MT03", ("MT03", "MT04"),
                  "MT13 default: the prior ultimate of Bornhuetter–Ferguson"),
        Parameter("measure", "incurred", ("incurred", "paid"), "MT13 default, as MT10"),
    ),
    "MT14": (
        Parameter("curve", "exponential_decay", tuple(c.value for c in Curve),
                  "MT14 default curve"),
        Parameter("fit_from_age", None, ANY,
                  "MT14 default: from the first column with a factor above 1", minimum=0),
        Parameter("min_points", 3, ANY, "MT14 default", minimum=2, whole=True),
        Parameter("extension_periods", 100, ANY, "MT14 default (decision 0608)",
                  minimum=0, whole=True),
        Parameter("remainder_warning", 0.005, ANY, "MT14 default (decision 0614)", minimum=0),
    ),
    "MT15": (
        Parameter("claim_counts", "ultimate", ("ultimate", "reported"),
                  "MT15 default: ultimate counts of MT16"),
        Parameter("future_index", "trend", ("trend", "assumption"),
                  "MT15 default: log-linear trend of the last diagonals"),
        Parameter("trend_periods", 5, ANY, "MT15 default", minimum=2, whole=True),
        Parameter("future_rate", None, ANY,
                  "MT15: annual rate of the future index, used with future_index assumption",
                  minimum=-0.99),
    ),
    "MT16": (
        Parameter("severity_measure", "incurred", ("incurred", "paid"), "MT16 default"),
        Parameter("maturity_for_trend", 0.9, ANY, "MT16 default", minimum=0),
        Parameter("min_trend_origins", 3, ANY, "MT16 default", minimum=2, whole=True),
        Parameter("value_basis", "INFLATION_ADJUSTED", ("INFLATION_ADJUSTED", "NOMINAL"),
                  "MT16 default: value-date prices when the price index is loaded"),
        Parameter("separate_catastrophes", True, ANY,
                  "MT16 default: catastrophe claims projected apart"),
    ),
    "MT22": (
        Parameter("horizons_months", "12,24,36", ANY,
                  "MT22 default: past cut-offs 12, 24 and 36 months back"),
        Parameter("mature_at", 0.95, ANY, "MT22 default", minimum=0),
        Parameter("backtest_simulations", 1000, ANY, "MT22 default (decision 0618)",
                  minimum=2, whole=True),
        Parameter("past_selections", "rerun", ("rerun", "manifests"),
                  "MT22 default: the default selection rules re-run at the past cut-off"),
    ),
}  # fmt: skip


def _checked(method: str, p: Parameter, entry: Assumption) -> Value:
    value = entry.value
    where = f"{method} {p.name}"
    if p.allowed is not None:
        if str(value) not in p.allowed:
            raise AssumptionError(f"{where} {value!r}: allowed {', '.join(p.allowed)}")
        return str(value)
    if isinstance(p.default, bool):
        if not isinstance(value, bool):
            raise AssumptionError(f"{where} {value!r}: true or false")
        return value
    if isinstance(p.default, str):  # a list of whole months, as in "12,24"
        try:
            months = [int(x) for x in str(value).split(",")]
        except ValueError:
            raise AssumptionError(f"{where} {value!r}: whole months separated by commas") from None
        return ",".join(str(m) for m in months)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AssumptionError(f"{where} {value!r}: not a number")
    if p.minimum is not None and value < p.minimum:
        raise AssumptionError(f"{where} {value!r}: below {p.minimum:g}")
    if p.whole and float(value) != int(value):
        raise AssumptionError(f"{where} {value!r}: not a whole number")
    return int(value) if p.whole else float(value)


def parameters(
    method: str, scope: str, register: AssumptionsRegister
) -> tuple[dict[str, Value], list[Assumption]]:
    """The parameters of `method` for `scope`, and one entry in force for each."""
    values: dict[str, Value] = {}
    entries: list[Assumption] = []
    for p in PARAMETERS[method]:
        found = register.find(method, p.name, scope)
        unknown = [t for t in found if t]
        if unknown:
            raise AssumptionError(f"{method} {p.name} applies to the whole scope, not {unknown}")
        user = found.get("")
        value = p.default if user is None else _checked(method, p, user)
        values[p.name] = value
        entries.append(_entry(method, p.name, scope, "", value, p.default, user, p.why))
    if (
        method == "MT15"
        and values["future_index"] == "assumption"
        and values["future_rate"] is None
    ):
        raise AssumptionError("MT15 future_index assumption needs a future_rate entry")
    return values, entries


def horizons(value: Value) -> tuple[int, ...]:
    """MT22 horizons_months as whole months."""
    return tuple(int(x) for x in str(value).split(","))


def number(value: Value) -> float:
    """A numeric parameter value (checked by `parameters`)."""
    assert isinstance(value, int | float) and not isinstance(value, bool), value
    return float(value)


def chain_ladder_with_tail(
    cumulative: np.ndarray,
    *,
    origins: Sequence[str],
    ages: Sequence[int],
    scope: str,
    register: AssumptionsRegister,
    calendar: np.ndarray | None = None,
    **options: object,
) -> tuple[ChainLadder | Skipped, TailFit | Skipped | None, list[Assumption]]:
    """MT02 as judged, MT14 fitted on its selected factors, and the MT02 tail replaced by the
    fitted one when the register selects a curve (MT14 `selected_curve`, target ""). The
    entries in force name the curve, the fit range and the tail used (MT14)."""
    chain, entries = chain_ladder_judged(
        cumulative, origins=origins, ages=ages, scope=scope, register=register,
        calendar=calendar, **options,  # type: ignore[arg-type]
    )  # fmt: skip
    if isinstance(chain, Skipped):
        return chain, None, entries
    values, tail_entries = parameters("MT14", scope, register)
    entries += tail_entries
    start = values["fit_from_age"]
    fit = fit_tail(
        chain.factors, ages,
        curve=Curve(str(values["curve"])),
        fit_from_age=None if start is None else int(number(start)),
        min_points=int(number(values["min_points"])),
        extension_periods=int(number(values["extension_periods"])),
        remainder_warning=number(values["remainder_warning"]),
    )  # fmt: skip
    selected = register.find("MT14", "selected_curve", scope).get("")
    if selected is None:
        return chain, fit, entries
    if register.find("MT02", "tail_factor", scope).get(""):
        raise AssumptionError("MT02 tail_factor and MT14 selected_curve both set a tail")
    if str(selected.value) not in {c.value for c in Curve}:
        allowed = ", ".join(c.value for c in Curve)
        raise AssumptionError(f"MT14 selected_curve {selected.value!r}: allowed {allowed}")
    if isinstance(fit, Skipped):
        raise AssumptionError(f"MT14 selected_curve: the tail could not be fitted: {fit.reason}")
    curve_fit = fit.fits[Curve(str(selected.value))]
    if isinstance(curve_fit, Skipped):
        raise AssumptionError(f"MT14 selected_curve {selected.value}: {curve_fit.reason}")
    tail = curve_fit.tail_factor
    # the run's own tail setting (passed in `options` by the module) gives way to the fitted one
    rest = {k: v for k, v in options.items() if k != "tail_factor"}
    rerun, _ = chain_ladder_judged(
        cumulative, origins=origins, ages=ages, scope=scope, register=register,
        calendar=calendar, tail_factor=tail, **rest,  # type: ignore[arg-type]
    )  # fmt: skip
    entries = [e for e in entries if not (e.method == "MT02" and e.name == "tail_factor")]
    first = ages[curve_fit.columns[0]]
    entries.insert(
        0,
        Assumption(
            method="MT02", name="tail_factor", scope=scope, value=tail, default=TAIL_DEFAULT,
            who=selected.who, when=selected.when,
            why=f"MT14 {selected.value} tail fitted from {first} months: {selected.why}",
        ),
    )  # fmt: skip
    entries.append(
        _entry("MT14", "selected_curve", scope, "", str(selected.value), None, selected, "")
    )
    return rerun, fit, entries
