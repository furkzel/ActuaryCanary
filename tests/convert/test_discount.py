"""The discounting context (CV10): naming the curve and the date, the timing of a cash flow, the
factors, and why a curve is not available."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.discount import (
    DiscountSettings,
    Timing,
    resolve_discount,
)
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.methods.assumptions import (
    Assumption,
    AssumptionError,
    AssumptionsRegister,
)

CUT_OFF = date(2025, 12, 31)


def rates(*days: date, currency: str = "TRY", rate: float = 0.10) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "curve_id": "C",
                "date": day,
                "tenor_months": months,
                "rate": rate,
                "rate_type": "SPOT",
                "compounding": "ANNUAL",
                "currency": currency,
                "source": "TEST",
                SOURCE_ROW: 2 + i * 2 + k,
            }
            for i, day in enumerate(days)
            for k, months in enumerate((12, 24))
        ]
    )


def register(**values: float | str) -> AssumptionsRegister:
    return AssumptionsRegister(
        entries=tuple(
            Assumption(method="CV10", name=name, value=value, who="analyst", why="test")
            for name, value in values.items()
        )
    )


def resolve(settings: DiscountSettings | None = None, **kwargs):  # noqa: ANN201, ANN003
    return resolve_discount(
        settings or DiscountSettings(curve_id="C"),
        kwargs.pop("register", AssumptionsRegister()),
        kwargs.pop("frame", rates(CUT_OFF)),
        CUT_OFF,
        kwargs.pop("currency", "TRY"),
    )


def test_without_a_named_curve_there_is_no_discounting_and_the_reason_says_so() -> None:
    context = resolve(DiscountSettings())
    assert not context.available and "no curve is named" in context.reason
    assert context.discount_date == CUT_OFF


def test_a_curve_that_is_named_but_not_loaded_says_so() -> None:
    assert "no interest rates were loaded" in resolve(frame=None).reason
    assert "not in the interest rates" in resolve(DiscountSettings(curve_id="Z")).reason


def test_the_original_currency_view_has_no_reporting_currency_to_match() -> None:
    assert "ORIGINAL" in resolve(currency=None).reason


def test_a_curve_in_another_currency_is_unavailable() -> None:
    context = resolve(frame=rates(CUT_OFF, currency="EUR"))
    assert not context.available and "EUR" in context.reason and "TRY" in context.reason


def test_the_curve_is_the_latest_one_on_or_before_the_discount_date() -> None:
    context = resolve(frame=rates(date(2025, 11, 30), CUT_OFF, date(2026, 1, 31)))
    assert context.curve is not None and context.curve.curve_date == CUT_OFF
    assert context.curve_age_days == 0 and context.findings == ()


def test_an_old_curve_is_used_and_flagged_by_dv_irt_08() -> None:
    context = resolve(frame=rates(date(2025, 9, 30)))
    assert context.curve is not None and context.curve_age_days == 92
    assert [f.rule for f in context.findings] == ["DV-IRT-08"]
    # the limit is a setting: a longer one accepts the curve silently
    lenient = resolve(
        DiscountSettings(curve_id="C", max_curve_age_days=100), frame=rates(date(2025, 9, 30))
    )
    assert lenient.findings == ()


def test_no_curve_on_or_before_the_discount_date_makes_the_basis_unavailable() -> None:
    context = resolve(frame=rates(date(2026, 1, 31)))
    assert not context.available and "DV-IRT-08" in context.reason


def test_the_discount_date_comes_from_the_register_then_the_settings_then_the_cut_off() -> None:
    settings = DiscountSettings(curve_id="C", discount_date=date(2025, 12, 15))
    assert resolve(settings, frame=rates(date(2025, 12, 1))).discount_date == date(2025, 12, 15)
    from_register = resolve(
        settings, register=register(discount_date="2025-11-30"), frame=rates(date(2025, 11, 30))
    )
    assert from_register.discount_date == date(2025, 11, 30)
    with pytest.raises(AssumptionError, match="not a date"):
        resolve(settings, register=register(discount_date="soon"))


def test_a_register_entry_names_the_curve_and_wins_over_the_option() -> None:
    other = pl.concat([rates(CUT_OFF), rates(CUT_OFF).with_columns(pl.lit("D").alias("curve_id"))])
    context = resolve(DiscountSettings(curve_id="C"), register=register(curve_id="D"), frame=other)
    assert context.curve is not None and context.curve.curve_id == "D"
    by_name = {e.name: e for e in context.entries}
    assert by_name["curve_id"].who == "analyst" and by_name["curve_id"].value == "D"


def test_the_entries_in_force_say_who_chose_each_value() -> None:
    context = resolve(DiscountSettings(curve_id="C", discount_date=CUT_OFF))
    by_name = {e.name: e for e in context.entries}
    assert by_name["curve_id"].who == "run settings" and by_name["curve_id"].default is None
    assert by_name["discount_date"].who == "run settings"
    assert by_name["timing"].who == "default" and by_name["timing"].value == "mid_period"
    assert by_name["max_curve_age_days"].value == 31 and by_name["tail_payment_years"].value == 5


def test_the_timing_places_a_cash_flow_in_its_period() -> None:
    start, end = date(2026, 1, 31), date(2027, 1, 31)  # start exclusive
    middle = resolve().payment_date(start, end)
    assert middle == date(2026, 8, 1)  # 365 days // 2 = 182 days after the start
    assert (
        resolve(DiscountSettings(curve_id="C", timing=Timing.START_OF_PERIOD)).payment_date(
            start, end
        )
        == start
    )
    assert (
        resolve(DiscountSettings(curve_id="C", timing=Timing.END_OF_PERIOD)).payment_date(
            start, end
        )
        == end
    )
    assert resolve(register=register(timing="end_of_period")).timing is Timing.END_OF_PERIOD


def test_factors_follow_the_curve_and_are_one_at_or_before_the_discount_date() -> None:
    context = resolve()
    dates = [date(2025, 6, 30), CUT_OFF, date(2026, 12, 31), date(2030, 12, 31)]
    factors = context.factors(dates)
    assert factors[:2].tolist() == [1.0, 1.0]
    years = (date(2026, 12, 31) - CUT_OFF).days / 365.25
    assert factors[2] == pytest.approx(1.1**-years, rel=1e-13)
    assert context.beyond_curve(dates) == 1  # only the last lies beyond two years
    assert np.all(np.diff(factors) <= 0)


def test_whole_number_settings_in_the_register_are_checked() -> None:
    with pytest.raises(AssumptionError, match="whole number"):
        resolve(register=register(tail_payment_years=2.5))
    assert resolve(register=register(tail_payment_years=3)).tail_payment_years == 3
