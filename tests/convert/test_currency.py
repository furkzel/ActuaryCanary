"""CV01 currency conversion: rate types, fallbacks, reciprocals, the constant development rate."""

from datetime import date

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.convert.currency import (
    FLAG_AVERAGE,
    FLAG_EARLIER_SPOT,
    FLAG_SPOT_FOR_END,
    Rule,
    convert,
    lookup_rates,
)
from actuarycanary.convert.rates import development_rates
from tests.convert.fixtures import FEB, JAN, MAR, market

# daily rates are sparse on purpose: the fallbacks are what these tests are about
SPARSE = [
    ("USD/TRY", "FX_SPOT", date(2024, 1, 12), 31.0),
    ("USD/TRY", "FX_PERIOD_AVERAGE", JAN, 30.0),
    ("USD/TRY", "FX_PERIOD_END", JAN, 31.5),
    ("TRY/EUR", "FX_SPOT", date(2024, 2, 27), 0.02),  # EUR/TRY 50
    ("TRY/EUR", "FX_PERIOD_END", JAN, 0.025),  # 40
    ("TRY/EUR", "FX_PERIOD_END", MAR, 0.01),  # 100
]


def _rates(
    rule: Rule, currency: str, day: date, rows: list = SPARSE, target: str = "TRY"
) -> tuple[float | None, str]:
    keys = pl.DataFrame({"currency": [currency], "day": [day]})
    row = lookup_rates(market(rows), target, keys, rule).row(0, named=True)
    return row["rate"], row["flag"]


def test_cv01_flow_uses_the_spot_rate_of_the_booking_date() -> None:
    assert _rates(Rule.FLOW, "USD", date(2024, 1, 12)) == (31.0, "")


def test_cv01_flow_without_a_spot_rate_takes_the_nearest_earlier_one_and_flags_it() -> None:
    assert _rates(Rule.FLOW, "USD", date(2024, 1, 19)) == (31.0, FLAG_EARLIER_SPOT)  # 7 days


def test_cv01_flow_gap_over_the_lookback_or_no_earlier_spot_takes_the_period_average() -> None:
    assert _rates(Rule.FLOW, "USD", date(2024, 1, 20)) == (30.0, FLAG_AVERAGE)  # 8 days
    assert _rates(Rule.FLOW, "USD", date(2024, 1, 5)) == (30.0, FLAG_AVERAGE)  # nothing earlier


def test_cv01_flow_without_any_applicable_rate_is_not_converted() -> None:
    assert _rates(Rule.FLOW, "USD", date(2024, 4, 10)) == (None, "")
    assert _rates(Rule.FLOW, "GBP", date(2024, 1, 12)) == (None, "")


def test_cv01_flow_derived_from_valuations_uses_the_period_average_of_its_month() -> None:
    assert _rates(Rule.DERIVED_FLOW, "USD", date(2024, 1, 31)) == (30.0, "")
    assert _rates(Rule.DERIVED_FLOW, "USD", date(2024, 2, 29)) == (None, "")  # no February


def test_cv01_stock_uses_the_period_end_rate_of_the_valuation_month() -> None:
    assert _rates(Rule.STOCK, "USD", JAN) == (31.5, "")


def test_cv01_stock_without_period_end_takes_the_spot_rate_and_flags_it() -> None:
    assert _rates(Rule.STOCK, "EUR", FEB) == (pytest.approx(50.0), FLAG_SPOT_FOR_END)
    assert _rates(Rule.STOCK, "USD", FEB) == (None, "")  # no spot within 7 days either


def test_cv01_reciprocal_pair_is_used_and_cross_rates_are_not() -> None:
    assert _rates(Rule.STOCK, "EUR", JAN) == (pytest.approx(40.0), "")
    assert _rates(Rule.STOCK, "TRY", JAN, target="EUR") == (pytest.approx(0.025), "")
    assert _rates(Rule.STOCK, "USD", JAN, target="EUR") == (None, "")  # via TRY: not formed


def test_cv01_the_target_currency_has_rate_one_without_market_data() -> None:
    keys = pl.DataFrame({"currency": ["TRY", "USD"], "day": [JAN, JAN]})
    found = lookup_rates(None, "TRY", keys, Rule.FLOW).sort("currency")
    assert dict(zip(found["currency"], found["rate"], strict=True)) == {"TRY": 1.0, "USD": None}


def _flows() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "currency": ["TRY", "USD", "USD", "EUR", "GBP"],
            "booking_date": [JAN, date(2024, 1, 12), date(2024, 1, 5), date(2024, 1, 31), JAN],
            "amount": [10.0, 2.0, 3.0, 4.0, 5.0],
        }
    )


def test_cv01_converted_amounts_flags_and_amounts_left_in_original_currency() -> None:
    done = convert(
        _flows(),
        ["amount"],
        day="booking_date",
        rule=Rule.STOCK,
        target="TRY",
        market=market(SPARSE),
    )
    assert done.frame["amount"].to_list() == [
        10.0,
        2 * 31.5,
        3 * 31.5,
        pytest.approx(4 * 40.0),
        None,
    ]
    assert done.not_converted.to_dicts() == [{"currency": "GBP", "rows": 1, "amount": 5.0}]
    flows = convert(
        _flows(),
        ["amount"],
        day="booking_date",
        rule=Rule.FLOW,
        target="TRY",
        market=market(SPARSE),
    )
    assert flows.frame["amount"].to_list()[1:3] == [2 * 31.0, 3 * 30.0]  # exact spot, average
    assert flows.flagged().to_dicts() == [{"rate_flag": FLAG_AVERAGE, "rows": 1}]


def test_cv01_without_market_data_foreign_amounts_stay_unconverted_and_are_reported_apart() -> None:
    done = convert(
        _flows(), ["amount"], day="booking_date", rule=Rule.FLOW, target="TRY", market=None
    )
    assert done.frame["amount"].to_list() == [10.0, None, None, None, None]
    assert done.not_converted.sort("currency").to_dicts() == [
        {"currency": "EUR", "rows": 1, "amount": 4.0},
        {"currency": "GBP", "rows": 1, "amount": 5.0},
        {"currency": "USD", "rows": 2, "amount": 5.0},
    ]


def test_cv01_development_rate_is_one_stock_rate_for_every_currency() -> None:
    rates = development_rates("TRY", ["TRY", "USD", "EUR", "GBP"], market(), MAR)
    assert rates.rates == {"TRY": 1.0, "USD": 34.0, "EUR": pytest.approx(100.0)}
    assert rates.missing == ("GBP",)
    earlier = development_rates("TRY", ["USD", "EUR"], market(), FEB)
    assert earlier.rates["USD"] == 32.0 and earlier.rates["EUR"] == pytest.approx(62.5)
    sparse = development_rates("TRY", ["EUR"], market(SPARSE), FEB)
    assert sparse.rates["EUR"] == pytest.approx(50.0)
    assert sparse.flags == {"EUR": FLAG_SPOT_FOR_END}


def test_cv01_development_rates_without_market_data_cover_the_reporting_currency_only() -> None:
    rates = development_rates("TRY", ["TRY", "USD"], None, MAR)
    assert rates.rates == {"TRY": 1.0} and rates.missing == ("USD",)


def _round_trip(rule: Rule, amounts: list[float]) -> None:
    """Converting into TRY and back uses the rate and its reciprocal, so it is the identity."""
    frame = pl.DataFrame(
        {
            "currency": ["USD", "EUR"] * 3,
            "day": [JAN, JAN, FEB, FEB, MAR, MAR],
            "amount": amounts,
        }
    )
    there = convert(frame, ["amount"], day="day", rule=rule, target="TRY", market=market())
    for currency in ("USD", "EUR"):
        part = there.frame.filter(pl.col("currency") == currency)
        back = part.with_columns(pl.lit("TRY").alias("currency")).drop("rate", "rate_flag")
        home = convert(back, ["amount"], day="day", rule=rule, target=currency, market=market())
        original = frame.filter(pl.col("currency") == currency)["amount"]
        for got, want in zip(home.frame["amount"], original, strict=True):
            assert got == pytest.approx(want, rel=1e-12, abs=1e-6)


@pytest.mark.parametrize("rule", list(Rule))
def test_cv01_converting_and_converting_back_returns_the_original(rule: Rule) -> None:
    _round_trip(rule, [1234.56, -0.07, 1e9, 3.0, -250000.5, 0.0])


@pytest.mark.slow
@pytest.mark.parametrize("rule", list(Rule))
@given(
    amounts=st.lists(
        st.floats(min_value=-1e9, max_value=1e9, allow_nan=False), min_size=6, max_size=6
    )
)
def test_cv01_property_converting_and_converting_back_returns_the_original(
    rule: Rule, amounts: list[float]
) -> None:
    _round_trip(rule, amounts)
