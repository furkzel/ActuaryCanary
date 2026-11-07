"""From the assumptions register to the parameters of MT19, and back to the entries in force
(as `severity.judgement` does for MT17 and MT18).

A register entry replaces the platform default of a parameter for a scope: the segment and the
word survival, for example NON_LIFE/survival. The covariates are one text entry, the names
separated by commas. The entries in force come out with the default each one replaces; a value
other than the specification default that the caller passed is a run setting.
"""

import math
from typing import Any

from actuarycanary.methods.assumptions import (
    Assumption,
    AssumptionError,
    AssumptionsRegister,
)
from actuarycanary.methods.judgement import SETTINGS_WHO, _entry
from actuarycanary.methods.survival import analysis as an

METHOD = "MT19"


def _text(entry: Assumption, name: str, allowed: tuple[str, ...]) -> str:
    if str(entry.value) not in allowed:
        raise AssumptionError(f"MT19 {name} {entry.value!r}: allowed {', '.join(allowed)}")
    return str(entry.value)


def mt19_judged(
    register: AssumptionsRegister,
    scope: str,
    *,
    event: str = an.EVENT_CLOSED,
    covariates: tuple[str, ...] = an.COVARIATES,
    ties: str = an.TIES_DEFAULT,
    confidence: float = an.CONFIDENCE,
    time_unit: str = an.TIME_UNIT,
) -> tuple[dict[str, Any], list[Assumption]]:
    """Options of the survival analysis for `scope` with the register's entries applied, and
    every judgement MT19 will use as an entry in force."""
    options: dict[str, Any] = {}
    entries: list[Assumption] = []

    def pick(name: str) -> Assumption | None:
        found = register.find(METHOD, name, scope)
        wrong = [t for t in found if t]
        if wrong:
            raise AssumptionError(f"MT19 {name} applies to the whole scope, not {wrong}")
        return found.get("")

    def put(name: str, value: Any, default: Any, user: Assumption | None, why: str) -> None:
        shown = ", ".join(value) if isinstance(value, tuple) else value
        shown_default = ", ".join(default) if isinstance(default, tuple) else default
        who = SETTINGS_WHO if shown != shown_default else "default"
        entries.append(_entry(METHOD, name, scope, "", shown, shown_default, user, why, who=who))

    user = pick("event")
    options["event"] = _text(user, "event", an.EVENTS) if user else event
    put("event", options["event"], an.EVENT_CLOSED, user,
        "MT19 default: the event is the first closing in any closed status")  # fmt: skip

    user = pick("covariates")
    if user:
        chosen = tuple(c.strip() for c in str(user.value).split(",") if c.strip())
        wrong = [c for c in chosen if c not in an.COVARIATE_CHOICES]
        if not chosen or wrong:
            raise AssumptionError(
                f"MT19 covariates {user.value!r}: names separated by commas from "
                f"{', '.join(an.COVARIATE_CHOICES)}"
            )
        options["covariates"] = tuple(dict.fromkeys(chosen))
    else:
        options["covariates"] = tuple(covariates)
    put("covariates", options["covariates"], an.COVARIATES, user,
        "MT19 default: the line is the covariate of the Cox model")  # fmt: skip

    user = pick("ties")
    options["ties"] = _text(user, "ties", an.TIES) if user else ties
    put("ties", options["ties"], an.TIES_DEFAULT, user,
        "MT19 default: Efron handling of tied event times")  # fmt: skip

    user = pick("confidence")
    if user is not None and (
        isinstance(user.value, bool) or not isinstance(user.value, int | float)
    ):
        raise AssumptionError(f"MT19 confidence {user.value!r}: not a number")
    options["confidence"] = float(user.value) if user else float(confidence)  # type: ignore[arg-type]
    if not (0.0 < options["confidence"] < 1.0) or not math.isfinite(options["confidence"]):
        raise AssumptionError("MT19 confidence must lie between 0 and 1")
    put("confidence", options["confidence"], an.CONFIDENCE, user,
        "MT19 default: 95 per cent intervals")  # fmt: skip

    user = pick("time_unit")
    options["time_unit"] = _text(user, "time_unit", tuple(an.TIME_UNITS)) if user else time_unit
    put("time_unit", options["time_unit"], an.TIME_UNIT, user,
        "MT19 default: curves and percentiles in days")  # fmt: skip
    return options, entries
