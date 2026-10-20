"""The price index follows the chosen inflation path; exchange rates follow the differential."""

from datetime import date

import numpy as np
import pytest

from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.market import build_market
from actuarycanary.synthetic.scenario import load_with

QUIET = {
    "market": {
        "cpi": {"monthly_noise_sd": 0.0},
        "fx": [
            {
                "series_id": "USD/TRY",
                "start": 2.95,
                "drift": "inflation_differential",
                "foreign_inflation": 0.03,
                "monthly_vol": 0.0,
            },
            {
                "series_id": "EUR/TRY",
                "start": 3.25,
                "drift": "inflation_differential",
                "foreign_inflation": 0.02,
                "monthly_vol": 0.0,
            },
        ],
    }
}


@pytest.fixture(scope="module")
def quiet():
    scenario = load_with("baseline", QUIET)
    return scenario, build_market(scenario, Streams(scenario.meta.seed))


def test_the_index_starts_at_its_base_value(quiet):
    _, market = quiet
    assert market.cpi[0] == 100.0
    assert market.price_factor(np.array([to_day(date(2016, 1, 15))]))[0] == 1.0


def test_without_noise_each_year_grows_by_exactly_its_annual_rate(quiet):
    scenario, market = quiet
    for year, rate in scenario.market.cpi.annual_rate_by_year.items():
        if year == 2016:
            continue
        december = market.cpi_at(np.array([to_day(date(year, 12, 31))]))[0]
        previous = market.cpi_at(np.array([to_day(date(year - 1, 12, 31))]))[0]
        assert december / previous == pytest.approx(1 + rate, rel=1e-6)


def test_noise_moves_the_path_but_not_the_trend():
    scenario = load_with("baseline", {})
    market = build_market(scenario, Streams(scenario.meta.seed))
    december_2023 = market.cpi_at(np.array([to_day(date(2023, 12, 31))]))[0]
    december_2024 = market.cpi_at(np.array([to_day(date(2024, 12, 31))]))[0]
    assert abs(december_2024 / december_2023 - 1.45) < 0.06  # annual rate 45 per cent


def test_the_index_continues_past_the_cut_off_at_the_last_listed_rate(quiet):
    scenario, market = quiet
    cut_off = to_day(scenario.meta.valuation.last)
    later = market.cpi_at(np.array([cut_off + 365]))[0]
    assert later / market.cpi_at(np.array([cut_off]))[0] == pytest.approx(1.33, rel=0.01)


def test_without_volatility_the_rate_follows_the_inflation_differential(quiet):
    _, market = quiet
    start, end = to_day(date(2017, 1, 1)), to_day(date(2018, 1, 1))
    ratio = market.fx_at("USD", np.array([end]))[0] / market.fx_at("USD", np.array([start]))[0]
    assert ratio == pytest.approx(1.11 / 1.03, rel=1e-3)
    assert market.fx_at("USD", np.array([0]))[0] == 2.95  # before the base date: the first rate


def test_exchange_rates_start_at_the_given_rate_and_stay_positive():
    scenario = load_with("baseline", {})
    market = build_market(scenario, Streams(scenario.meta.seed))
    assert market.fx["EUR"][0] == 3.25
    assert (market.fx["USD"] > 0).all()
