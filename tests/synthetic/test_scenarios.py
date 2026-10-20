"""What each scenario changes in the simulated world, seen through the truth."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.build import simulate
from actuarycanary.synthetic.claims import SHOCK, Cumulative
from actuarycanary.synthetic.days import to_day


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


def test_large_loss_adds_three_shocks_on_the_chosen_days():
    sim = simulate("large_loss", "tiny")
    w = sim.world
    shocks = np.flatnonzero(w.c_kind == SHOCK)
    assert sorted(w.c_occ[shocks].tolist()) == sorted(
        to_day(date(y, m, d)) for y, m, d in [(2022, 5, 10), (2023, 9, 12), (2024, 3, 2)]
    )
    base = simulate("baseline", "tiny")
    largest = sim.truth["ultimates"].select(pl.col("ultimate_gross").max()).item()
    baseline_largest = base.truth["ultimates"].select(pl.col("ultimate_gross").max()).item()
    assert largest > 3 * baseline_largest


def test_large_loss_shocks_are_not_capped_by_the_sum_insured():
    sim = simulate("large_loss", "tiny")
    w = sim.world
    shock = int(np.flatnonzero((w.c_kind == SHOCK) & (w.c_line == "PROPERTY"))[0])
    assert w.c_cost[shock] == pytest.approx(60_000_000.0)


def test_messy_headers_has_the_same_world_as_the_baseline_and_only_the_layout_differs():
    base, messy = simulate("baseline", "tiny"), simulate("messy_headers", "tiny")
    assert (base.world.p_amount == messy.world.p_amount).all()
    assert base.clean["claim_valuations"].equals(messy.clean["claim_valuations"])
    assert (
        messy.frames["premiums"]["premiums"].height > base.frames["premiums"]["premiums"].height
    )  # repeated rows
