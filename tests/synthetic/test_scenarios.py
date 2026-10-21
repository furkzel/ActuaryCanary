"""What each scenario changes in the simulated world, seen through the truth."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.build import anomalies, simulate
from actuarycanary.synthetic.claims import SHOCK, Cumulative
from actuarycanary.synthetic.days import to_day
from tests.synthetic.conftest import simulate_with


def review_ratios(sim, line: str) -> tuple[np.ndarray, np.ndarray]:
    """Case reserve estimate over the true remaining cost at that day's prices, per review,
    for claims that are not nil and never reopened; with the review dates."""
    w = sim.world
    cum = Cumulative(w.p_claim, w.p_day, w.p_w).at(w.r_claim, w.r_day)[0]
    eligible = (w.c_line[w.r_claim] == line) & ~w.c_nil[w.r_claim] & ~w.has_reopen[w.r_claim]
    truth = w.c_cost[w.r_claim] * w.index_for(w.r_claim, w.r_day) * np.maximum(1.0 - cum, 1e-12)
    return (w.r_estimate / truth)[eligible], w.r_day[eligible]


def test_reserve_bias_is_the_chosen_bias_and_changes_on_the_chosen_date():
    sim = simulate("reserve_bias_change", "tiny")
    ratio, day = review_ratios(sim, "MOTOR_TPL")
    before, after = ratio[day < to_day(date(2022, 1, 1))], ratio[day >= to_day(date(2022, 1, 1))]
    assert len(before) == 0 or before.mean() == pytest.approx(
        0.90, abs=0.2
    )  # tiny window starts in 2022
    assert after.mean() == pytest.approx(1.45, abs=0.2)
    own_damage, own_day = review_ratios(sim, "MOTOR_OD")
    late = own_damage[own_day >= to_day(date(2023, 7, 1))]
    early = own_damage[own_day < to_day(date(2023, 7, 1))]
    assert late.mean() == pytest.approx(0.70, abs=0.12) and early.mean() == pytest.approx(
        1.05, abs=0.12
    )


def test_baseline_reserve_bias_follows_the_baseline_practice_change(baseline):
    ratio, day = review_ratios(baseline, "MOTOR_TPL")
    assert ratio[day >= to_day(date(2022, 1, 1))].mean() == pytest.approx(1.15, abs=0.2)


def test_reserve_strengthening_shows_in_incurred_not_in_paid_development():
    base, changed = simulate("baseline", "tiny"), simulate("reserve_bias_change", "tiny")
    assert base.world.p_amount.sum() == changed.world.p_amount.sum()  # the world itself is the same

    def open_reserve(sim):
        open_rows = sim.clean["claim_valuations"].filter(pl.col("status") == "OPEN")
        return open_rows["case_reserve"].sum()

    assert open_reserve(changed) != open_reserve(base)


def test_high_inflation_raises_the_price_level_and_the_nominal_cost_of_the_same_claims():
    base, high = simulate("baseline", "tiny"), simulate("high_inflation", "tiny")
    cut_off = np.array([to_day(date(2025, 12, 31))])
    assert high.market.price_factor(cut_off)[0] > 2 * base.market.price_factor(cut_off)[0]
    assert len(high.world) == len(base.world)  # frequency is unchanged
    motor = np.isin(base.world.c_line, ["MOTOR_OD", "MOTOR_TPL"])  # not tied to sums insured
    assert (high.world.c_cost[motor] == base.world.c_cost[motor]).all()  # same cost at base prices
    assert float(high.truth["ultimates"]["ultimate_gross"].sum()) > 1.5 * float(
        base.truth["ultimates"]["ultimate_gross"].sum()
    )
    motor_lines = ["MOTOR_OD", "MOTOR_TPL"]

    def motor_base_cost(sim):
        motor = sim.truth["ultimates"].filter(pl.col("line").is_in(motor_lines))
        return motor["ultimate_base_prices_try"].sum()

    assert motor_base_cost(high) == pytest.approx(motor_base_cost(base))


def test_high_inflation_is_listed_among_the_anomalies():
    sim = simulate("high_inflation", "tiny")
    years = [e for e in sim.scenario.market.cpi.annual_rate_by_year.items() if e[1] >= 0.5]
    assert [y for y, _ in years] == [2022, 2023, 2024, 2025]


THREE_SHOCKS = {
    "large_claims": [
        {"line": "PROPERTY", "date": "2022-05-10", "cost_base": 60_000_000},
        {"line": "MOTOR_TPL", "date": "2023-09-12", "cost_base": 25_000_000},
        {"line": "PROPERTY", "date": "2024-03-02", "cost_base": 45_000_000},
    ]
}


def test_fixed_large_claims_land_on_the_chosen_days():
    sim = simulate_with(THREE_SHOCKS)
    w = sim.world
    shocks = np.flatnonzero(w.c_kind == SHOCK)
    assert sorted(w.c_occ[shocks].tolist()) == sorted(
        to_day(date(y, m, d)) for y, m, d in [(2022, 5, 10), (2023, 9, 12), (2024, 3, 2)]
    )
    base = simulate("baseline", "tiny")
    largest = sim.truth["ultimates"].select(pl.col("ultimate_gross").max()).item()
    baseline_largest = base.truth["ultimates"].select(pl.col("ultimate_gross").max()).item()
    assert largest > 3 * baseline_largest


def test_large_claims_are_not_capped_by_the_sum_insured():
    sim = simulate_with(THREE_SHOCKS)
    w = sim.world
    shock = int(np.flatnonzero((w.c_kind == SHOCK) & (w.c_line == "PROPERTY"))[0])
    assert w.c_cost[shock] == pytest.approx(60_000_000.0)


def _with_large_events(scale: float, rate: float = 0.02):
    return simulate_with(
        {
            "lines": {
                "PROPERTY": {
                    "large_events": {
                        "per_exposure_year": rate,
                        "cost": {"dist": "lognormal", "median": 5_000_000, "sigma": 0.5},
                    }
                }
            },
            "sizes": {"tiny": {"portfolio_scale": scale}},
        }
    )


def _large_events(sim, line: str = "PROPERTY") -> int:
    w = sim.world
    return int(((w.c_label == "LARGE_LOSS_EVENT") & (w.c_line == line)).sum())


def test_large_events_follow_the_rate_per_exposure_and_grow_with_the_portfolio():
    small, big = _with_large_events(0.02), _with_large_events(0.04)
    for sim in (small, big):
        exposure = sim.truth["frequency_severity"].filter(pl.col("line") == "PROPERTY")
        expected = 0.02 * float(exposure["exposure_years"].to_numpy().sum())
        assert expected > 40
        assert abs(_large_events(sim) - expected) < 4 * expected**0.5  # a Poisson count
    assert 1.5 < _large_events(big) / _large_events(small) < 2.7


def test_large_events_are_listed_in_the_truth_and_touch_no_other_line():
    sim, plain = (
        _with_large_events(0.02),
        simulate_with({"sizes": {"tiny": {"portfolio_scale": 0.02}}}),
    )
    other = [i for i in range(len(sim.world)) if sim.world.c_line[i] == "MOTOR_OD"]
    same = [i for i in range(len(plain.world)) if plain.world.c_line[i] == "MOTOR_OD"]
    assert sim.world.c_occ[other].tolist() == plain.world.c_occ[same].tolist()
    assert sim.world.c_cost[other].tolist() == plain.world.c_cost[same].tolist()
    assert int((sim.world.c_kind == SHOCK).sum()) == _large_events(sim)  # nothing else is a shock
    listed = sim_anomalies(sim)
    assert listed.height == _large_events(sim)
    assert (listed["line"] == "PROPERTY").all()


def test_messy_headers_has_the_same_world_as_the_baseline_and_only_the_layout_differs():
    base, messy = simulate("baseline", "tiny"), simulate("messy_headers", "tiny")
    assert (base.world.p_amount == messy.world.p_amount).all()
    assert base.clean["claim_valuations"].equals(messy.clean["claim_valuations"])
    assert (
        messy.frames["premiums"]["premiums"].height > base.frames["premiums"]["premiums"].height
    )  # repeated rows


def sim_anomalies(sim) -> pl.DataFrame:
    empty = pl.DataFrame(
        schema={
            "fault_type": pl.String,
            "file": pl.String,
            "key": pl.String,
            "row": pl.Int64,
            "sheet_row": pl.Int64,
            "detail": pl.String,
        }
    )
    table = anomalies(sim, empty)
    return table.filter(pl.col("type") == "large_loss_event")
