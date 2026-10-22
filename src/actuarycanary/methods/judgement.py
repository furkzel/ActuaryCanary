"""From the assumptions register to method parameters, and back to the entries in force.

Each function reads the user entries for one scope (group and measure), turns them into the
parameters of a method and returns, next to them, every judgement the method will use: the
user's entry where there is one, otherwise the platform default with who = "default".
"""

from collections.abc import Sequence

import numpy as np

from actuarycanary.methods.assumptions import (
    DEFAULT_WHO,
    Assumption,
    AssumptionError,
    AssumptionsRegister,
    column_label,
    parse_cell,
)
from actuarycanary.methods.bornhuetter_ferguson import DATA_DERIVED_PRIOR, USER_PRIOR
from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.selection import BF_BELOW_MATURITY, Choice

TAIL_DEFAULT = 1.0  # MT02
SETTINGS_WHO = "run settings"
EXCLUDED, INCLUDED = "excluded", "included"


def _entry(
    method: str,
    name: str,
    scope: str,
    target: str,
    value: float | str | bool | None,
    default: float | str | bool | None,
    user: Assumption | None,
    why: str,
    who: str = DEFAULT_WHO,
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
        who=who,
        why=why,
    )


def _number(entry: Assumption) -> float:
    if isinstance(entry.value, bool) or not isinstance(entry.value, int | float):
        raise AssumptionError(
            f"{entry.method} {entry.name} {entry.target!r}: value {entry.value!r} is not a number"
        )
    return float(entry.value)


def chain_ladder_judged(
    cumulative: np.ndarray,
    *,
    origins: Sequence[str],
    ages: Sequence[int],
    scope: str,
    register: AssumptionsRegister,
    calendar: np.ndarray | None = None,
    average: Average = Average.VOLUME_WEIGHTED,
    n_diagonals: int | None = None,
    exclude_high_low: bool = False,
    tail_factor: float = TAIL_DEFAULT,
    min_origins: int = 3,
) -> tuple[ChainLadder | Skipped, list[Assumption]]:
    """MT02 with the register's exclusions, selected factors and tail factor for `scope`.

    `tail_factor` is the run setting; a register entry replaces it."""
    origins = list(origins)
    columns = [column_label(ages, j) for j in range(len(ages) - 1)]
    entries: list[Assumption] = []

    tail_entry = register.find("MT02", "tail_factor", scope).get("")
    tail = _number(tail_entry) if tail_entry else tail_factor
    who = DEFAULT_WHO if tail_factor == TAIL_DEFAULT else SETTINGS_WHO
    entries.append(
        _entry("MT02", "tail_factor", scope, "", tail, TAIL_DEFAULT, tail_entry,
               "MT02 default: no development after the last age (tail fitting is tier B)", who)
    )  # fmt: skip

    exclusions: list[tuple[int, int]] = []
    for target, entry in sorted(register.find("MT02", "exclusion", scope).items()):
        if entry.value is False:
            continue
        exclusions.append(parse_cell(target, origins, ages))
        entries.append(_entry("MT02", "exclusion", scope, target, EXCLUDED, INCLUDED, entry, ""))

    selected: dict[int, float] = {}
    chosen = register.find("MT02", "selected_factor", scope)
    for target, entry in chosen.items():
        if target not in columns:
            raise AssumptionError(f"selected factor for {target!r}: no such development column")
        selected[columns.index(target)] = _number(entry)

    result = chain_ladder(
        cumulative,
        average=average,
        n_diagonals=n_diagonals,
        exclusions=exclusions,
        exclude_high_low=exclude_high_low,
        tail_factor=tail,
        min_origins=min_origins,
        calendar=calendar,
        selected=selected,
    )
    if isinstance(result, ChainLadder):
        for j, column in enumerate(columns):
            entries.append(
                _entry("MT02", "selected_factor", scope, column, float(result.factors[j]),
                       float(result.averages[j]), chosen.get(column),
                       f"MT02 default: the {average.value.replace('_', '-')} average")
            )  # fmt: skip
    return result, entries


def prior_loss_ratios(
    method: str,
    name: str,
    origins: Sequence[str],
    scope: str,
    register: AssumptionsRegister,
    data_derived: float | None,
) -> tuple[np.ndarray, tuple[str, ...], list[Assumption]]:
    """Loss ratio per origin for MT03 (prior_loss_ratio) or MT05 (expected_loss_ratio): the
    register's entry for the origin, else its entry for the whole scope, else the Cape Cod
    ratio of the same triangle labelled data-derived (record 0011); NaN when none exists."""
    found = register.find(method, name, scope)
    unknown = [t for t in found if t and t not in origins]
    if unknown:
        raise AssumptionError(f"{method} {name}: no origin {', '.join(unknown)}")
    general = found.get("")
    ratios = np.full(len(origins), np.nan)
    sources: list[str] = []
    for i, origin in enumerate(origins):
        entry = found.get(origin, general)
        if entry is not None:
            ratios[i] = _number(entry)
            sources.append(USER_PRIOR)
        elif data_derived is not None:
            ratios[i] = data_derived
            sources.append(DATA_DERIVED_PRIOR)
        else:
            sources.append("none")
    default = "cape_cod"
    entries: list[Assumption] = []
    if general is not None:
        entries.append(_entry(method, name, scope, "", _number(general), default, general, ""))
    elif data_derived is not None and any(s == DATA_DERIVED_PRIOR for s in sources):
        entries.append(
            _entry(method, name, scope, "", data_derived, default, None,
                   f"{method} default: Cape Cod ratio of the same triangle, data-derived prior "
                   "(record 0011)")
        )  # fmt: skip
    for origin in origins:
        if origin in found:
            entry = found[origin]
            entries.append(_entry(method, name, scope, origin, _number(entry), default, entry, ""))
    return ratios, tuple(sources), entries


def future_inflation(scope: str, register: AssumptionsRegister) -> tuple[float | None, Assumption]:
    """MT07: annual inflation after the value date; None keeps results at value-date prices."""
    entry = register.find("MT07", "future_inflation", scope).get("")
    value = None if entry is None else _number(entry)
    if value is not None and value <= -1:
        raise AssumptionError(f"future inflation {value} is not above -100 per cent")
    record = _entry(
        "MT07", "future_inflation", scope, "", value, None, entry,
        "MT07 default: no assumption, results at value-date prices only (record 0012)",
    )  # fmt: skip
    return value, record


def selection_overrides(
    origins: Sequence[str], scope: str, register: AssumptionsRegister
) -> tuple[dict[int, Choice], float, list[Assumption]]:
    """MT10: per-origin method choices and the maturity threshold, with their entries."""
    threshold_entry = register.find("MT10", "bf_below_maturity", scope).get("")
    threshold = _number(threshold_entry) if threshold_entry else BF_BELOW_MATURITY
    entries = [
        _entry("MT10", "bf_below_maturity", scope, "", threshold, BF_BELOW_MATURITY,
               threshold_entry, "MT10 default, owner decision (record 0011)")
    ]  # fmt: skip
    overrides: dict[int, Choice] = {}
    for target, entry in sorted(register.find("MT10", "method", scope).items()):
        if target not in origins:
            raise AssumptionError(f"MT10 method: no origin {target!r}")
        try:
            choice = Choice(str(entry.value))
        except ValueError:
            allowed = ", ".join(c.value for c in Choice)
            raise AssumptionError(f"MT10 method {entry.value!r}: allowed {allowed}") from None
        overrides[list(origins).index(target)] = choice
        entries.append(
            _entry("MT10", "method", scope, target, choice.value, "maturity rule", entry, "")
        )
    return overrides, threshold, entries
