"""The discounting context of a run (CV10): which curve, which discount date, where in its period a
cash flow falls, and the discount factor of a payment date.

The curve and the date come from the user's register entries (method CV10) or, failing those,
from the run settings (`--curve`, `--discount-date`), which are recorded as entries by "run
settings". Without a named curve there is no discounting, and the context says why.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from actuarycanary.canonical.feeds import Finding
from actuarycanary.convert.yield_curve import (
    CurveUnavailableError,
    YieldCurve,
    build_curve,
    curve_date_for,
    forward_findings,
    years_between,
)
from actuarycanary.methods.assumptions import (
    ANY_SCOPE,
    DEFAULT_WHO,
    Assumption,
    AssumptionError,
    AssumptionsRegister,
)

METHOD = "CV10"
SETTINGS_WHO = "run settings"
CUT_OFF = "cut-off"


class Timing(StrEnum):
    MID_PERIOD = "mid_period"
    START_OF_PERIOD = "start_of_period"
    END_OF_PERIOD = "end_of_period"


class DiscountSettings(BaseModel):
    """The discounting options of a run; each is part of the manifest and so of the run id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    curve_id: str | None = None
    discount_date: date | None = None
    timing: Timing = Timing.MID_PERIOD
    max_curve_age_days: int = Field(default=31, ge=0)
    tail_payment_years: int = Field(default=5, ge=1)


@dataclass(frozen=True)
class DiscountContext:
    """What the discounted figures are computed with. `curve` is None, and `reason` says why,
    when no discounting is possible."""

    curve: YieldCurve | None
    reason: str
    discount_date: date
    timing: Timing
    tail_payment_years: int
    entries: tuple[Assumption, ...] = ()
    findings: tuple[Finding, ...] = ()
    curve_age_days: int = 0

    @property
    def available(self) -> bool:
        return self.curve is not None

    def payment_date(self, start: date, end: date) -> date:
        """Where a cash flow of the period (start exclusive, end) falls (CV10)."""
        if self.timing is Timing.START_OF_PERIOD:
            return start
        if self.timing is Timing.END_OF_PERIOD:
            return end
        return start + timedelta(days=(end - start).days // 2)

    def years(self, payment_dates: list[date]) -> np.ndarray:
        return np.array([years_between(self.discount_date, d) for d in payment_dates])

    def factors(self, payment_dates: list[date]) -> np.ndarray:
        """Discount factors; 1 at and before the discount date. Needs a curve."""
        assert self.curve is not None
        return self.curve.discount_factors(self.years(payment_dates))

    def beyond_curve(self, payment_dates: list[date]) -> int:
        """How many payment dates lie beyond the last tenor of the curve."""
        assert self.curve is not None
        return int((self.years(payment_dates) > self.curve.tenors[-1]).sum())


def _user(register: AssumptionsRegister, name: str) -> Assumption | None:
    return register.find(METHOD, name, ANY_SCOPE).get("")


def _entry(
    name: str,
    value: float | str | None,
    default: float | str | None,
    user: Assumption | None,
    from_settings: bool,
    why: str,
) -> Assumption:
    if user is not None:
        return Assumption(
            method=METHOD,
            name=name,
            value=value,
            default=default,
            who=user.who,
            when=user.when,
            why=user.why,
        )
    if from_settings:
        return Assumption(
            method=METHOD,
            name=name,
            value=value,
            default=default,
            who=SETTINGS_WHO,
            why=why,
        )
    return Assumption(
        method=METHOD, name=name, value=value, default=default, who=DEFAULT_WHO, why=why
    )


def _text(entry: Assumption | None) -> str | None:
    if entry is None or entry.value is None:
        return None
    return str(entry.value).strip() or None


def _whole(entry: Assumption, name: str) -> int:
    if (
        isinstance(entry.value, bool)
        or not isinstance(entry.value, int | float)
        or entry.value != int(entry.value)
        or entry.value < 0
    ):
        raise AssumptionError(f"{METHOD} {name}: value {entry.value!r} is not a whole number")
    return int(entry.value)


def resolve_discount(
    settings: DiscountSettings,
    register: AssumptionsRegister,
    rates: pl.DataFrame | None,
    cut_off: date,
    reporting_currency: str | None,
) -> DiscountContext:
    """The context of a run. `rates` are the canonical interest rates, None when none were
    loaded; `reporting_currency` None (the ORIGINAL view) leaves no curve to discount with."""
    curve_entry, date_entry = _user(register, "curve_id"), _user(register, "discount_date")
    timing_entry = _user(register, "timing")
    age_entry, tail_entry = (
        _user(register, "max_curve_age_days"),
        _user(register, "tail_payment_years"),
    )

    curve_id = _text(curve_entry) or settings.curve_id
    if date_entry is not None and _text(date_entry) is not None:
        try:
            discount_date = date.fromisoformat(str(_text(date_entry)))
        except ValueError as error:
            raise AssumptionError(
                f"{METHOD} discount_date: {_text(date_entry)!r} is not a date YYYY-MM-DD"
            ) from error
    else:
        discount_date = settings.discount_date or cut_off
    timing = Timing(_text(timing_entry) or settings.timing.value)
    max_age = _whole(age_entry, "max_curve_age_days") if age_entry else settings.max_curve_age_days
    tail_years = (
        _whole(tail_entry, "tail_payment_years") if tail_entry else settings.tail_payment_years
    )
    if tail_years < 1:
        raise AssumptionError(f"{METHOD} tail_payment_years must be at least 1")

    entries = (
        _entry("curve_id", curve_id, None, curve_entry,
               curve_id is not None and curve_entry is None, "named by --curve"),
        _entry("discount_date", discount_date.isoformat(), CUT_OFF, date_entry,
               settings.discount_date is not None and date_entry is None, "set by --discount-date"),
        _entry("timing", timing.value, Timing.MID_PERIOD.value, timing_entry, False,
               "CV10 default"),
        _entry("max_curve_age_days", max_age, 31, age_entry, False, "CV10 default"),
        _entry("tail_payment_years", tail_years, 5, tail_entry, False, "CV10 default"),
    )  # fmt: skip

    def unavailable(reason: str, findings: tuple[Finding, ...] = ()) -> DiscountContext:
        return DiscountContext(None, reason, discount_date, timing, tail_years, entries, findings)

    if curve_id is None:
        return unavailable(
            "no curve is named: name one with --curve or a register entry (CV10, curve_id)"
        )
    if reporting_currency is None:
        return unavailable(
            "the ORIGINAL currency view has no reporting currency to match the curve to (CV10)"
        )
    if rates is None:
        return unavailable(f"curve {curve_id} is named but no interest rates were loaded")
    found, reason = curve_date_for(rates, curve_id, discount_date)
    if found is None:
        return unavailable(reason)
    findings: list[Finding] = []
    age = (discount_date - found).days
    if age > max_age:
        findings.append(
            Finding(
                "interest_rates",
                "DV-IRT-08",
                "WARNING",
                1,
                f"curve {curve_id} of {found} is {age} days older than the discount date "
                f"{discount_date} (more than {max_age}): used",
            )
        )
    try:
        curve, notes = build_curve(rates, curve_id, found)
    except CurveUnavailableError as error:
        return unavailable(str(error), tuple(findings))
    findings += notes
    if curve.currency != reporting_currency:
        return unavailable(
            f"curve {curve_id} is in {curve.currency}, the reporting currency is "
            f"{reporting_currency} (CV10)",
            tuple(findings),
        )
    extra = forward_findings(curve)
    if extra is not None:
        findings.append(extra)
    return DiscountContext(
        curve, "", discount_date, timing, tail_years, entries, tuple(findings), age
    )
