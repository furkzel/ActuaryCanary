"""From the assumptions register to the parameters of MT17 and MT18, and back to the entries in
force (as `methods.judgement` does for the triangle methods).

A register entry replaces the platform default of a parameter for a scope (group and measure,
for example NON_LIFE/MOTOR_TPL/severity). The entries in force come out with the default each
one replaces: a user entry carries who, when and why; anything else is the platform default,
or a run setting when the caller passed a value other than the specification default.
"""

import math
from collections.abc import Sequence
from typing import Any

from actuarycanary.methods.assumptions import (
    DEFAULT_WHO,
    Assumption,
    AssumptionError,
    AssumptionsRegister,
)
from actuarycanary.methods.severity import evt, fitting
from actuarycanary.methods.severity.evt import MIN_EXCEEDANCES_FLOOR
from actuarycanary.methods.severity.sizes import ALL_NON_NIL, CLAIMS_USED, CLOSED_CLAIMS

SETTINGS_WHO = "run settings"


def _entry(
    method: str,
    name: str,
    scope: str,
    value: float | str | bool | None,
    default: float | str | bool | None,
    user: Assumption | None,
    why: str,
    target: str = "",
) -> Assumption:
    if user is not None:
        return Assumption(
            method=method,
            name=name,
            scope=scope,
            target=target,
            value=value,
            default=default,
            who=user.who,
            when=user.when,
            why=user.why,
        )
    return Assumption(
        method=method,
        name=name,
        scope=scope,
        target=target,
        value=value,
        default=default,
        who=DEFAULT_WHO if value == default else SETTINGS_WHO,
        why=why,
    )


def _number(entry: Assumption) -> float:
    if isinstance(entry.value, bool) or not isinstance(entry.value, int | float):
        raise AssumptionError(
            f"{entry.method} {entry.name} {entry.target!r}: value {entry.value!r} is not a number"
        )
    return float(entry.value)


def _claims_used(entry: Assumption) -> str:
    if entry.value not in CLAIMS_USED:
        raise AssumptionError(
            f"{entry.method} claims_used {entry.value!r}: allowed {', '.join(CLAIMS_USED)}"
        )
    return str(entry.value)


def mt17_judged(
    register: AssumptionsRegister,
    scope: str,
    *,
    claims_used: str = CLOSED_CLAIMS,
    truncation_point: float = 0.0,
    exclude_catastrophes: bool = True,
    significance: float = fitting.SIGNIFICANCE,
    limits: Sequence[float] = (),
) -> tuple[dict[str, Any], list[Assumption]]:
    """Options of `fit_severity` for `scope` with the register's entries applied, and every
    judgement MT17 will use as an entry. `limits` entries are one per limit, the target being
    the limit as written."""
    options: dict[str, Any] = {}
    entries: list[Assumption] = []

    def pick(name: str) -> Assumption | None:
        return register.find("MT17", name, scope).get("")

    user = pick("claims_used")
    options["claims_used"] = _claims_used(user) if user else claims_used
    entries.append(
        _entry("MT17", "claims_used", scope, options["claims_used"], CLOSED_CLAIMS, user,
               "MT17 default: closed claims, whose sizes are final")
    )  # fmt: skip

    user = pick("truncation_point")
    options["truncation_point"] = _number(user) if user else float(truncation_point)
    if options["truncation_point"] < 0:
        raise AssumptionError("MT17 truncation_point cannot be negative")
    entries.append(
        _entry("MT17", "truncation_point", scope, options["truncation_point"], 0.0, user,
               "MT17 default: no truncation")
    )  # fmt: skip

    user = pick("exclude_catastrophes")
    if user is not None and not isinstance(user.value, bool):
        raise AssumptionError("MT17 exclude_catastrophes must be true or false")
    options["exclude_catastrophes"] = bool(user.value) if user else exclude_catastrophes
    entries.append(
        _entry("MT17", "exclude_catastrophes", scope, options["exclude_catastrophes"], True, user,
               "MT17 default: catastrophe events are not single-claim severity")
    )  # fmt: skip

    user = pick("significance")
    options["significance"] = _number(user) if user else float(significance)
    if not 0.0 < options["significance"] < 1.0:
        raise AssumptionError("MT17 significance must lie between 0 and 1")
    entries.append(
        _entry("MT17", "significance", scope, options["significance"], fitting.SIGNIFICANCE, user,
               "MT17 default: a family is rejected below 0.05")
    )  # fmt: skip

    found = register.find("MT17", "limit", scope)
    chosen = [_number(e) for e in found.values()] if found else [float(v) for v in limits]
    if any(not math.isfinite(v) or v <= 0 for v in chosen):
        raise AssumptionError("MT17 limits must be positive numbers")
    options["limits"] = sorted(set(chosen))
    entries.extend(
        _entry("MT17", "limit", scope, _number(e), None, e, "", target=t)
        for t, e in sorted(found.items())
    )
    return options, entries


def mt18_judged(
    register: AssumptionsRegister,
    scope: str,
    *,
    claims_used: str = ALL_NON_NIL,
    fdr_level: float = evt.FDR_LEVEL,
    min_exceedances: int = evt.MIN_EXCEEDANCES,
) -> tuple[dict[str, Any], list[Assumption]]:
    """Options of `extreme_values` for `scope` with the register's entries applied."""
    options: dict[str, Any] = {}
    entries: list[Assumption] = []

    def pick(name: str) -> Assumption | None:
        return register.find("MT18", name, scope).get("")

    user = pick("claims_used")
    options["claims_used"] = _claims_used(user) if user else claims_used
    entries.append(
        _entry("MT18", "claims_used", scope, options["claims_used"], ALL_NON_NIL, user,
               "MT18 default: all non-nil claims, so the largest open claims count")
    )  # fmt: skip

    user = pick("fdr_level")
    options["fdr_level"] = _number(user) if user else float(fdr_level)
    if not 0.0 < options["fdr_level"] < 1.0:
        raise AssumptionError("MT18 fdr_level must lie between 0 and 1")
    entries.append(
        _entry("MT18", "fdr_level", scope, options["fdr_level"], evt.FDR_LEVEL, user,
               "MT18 default: false discovery rate of ForwardStop (Bader, Yan and Zhang 2018)")
    )  # fmt: skip

    user = pick("min_exceedances")
    value = _number(user) if user else float(min_exceedances)
    if value < MIN_EXCEEDANCES_FLOOR or value != int(value):
        raise AssumptionError(
            f"MT18 min_exceedances must be a whole number of at least {MIN_EXCEEDANCES_FLOOR}"
        )
    options["min_exceedances"] = int(value)
    entries.append(
        _entry("MT18", "min_exceedances", scope, options["min_exceedances"], evt.MIN_EXCEEDANCES,
               user, "MT18 default: fewest excesses for a fit at a threshold")
    )  # fmt: skip
    return options, entries
