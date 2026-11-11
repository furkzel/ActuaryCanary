"""Claim size of a sum-insured line follows the index the scenario declares (record 0373).

The hand-checkable form: a death claim pays one amount, the sum insured of its policy, so the
paid amount divided by the sum insured at base-date prices is the index the generator applied.
"""

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.days import to_day, year_of
from actuarycanary.synthetic.scenario import load_scenario
from actuarycanary.synthetic.truth import claim_size_index
from tests.synthetic.conftest import simulate_with

LINE = "GROUP_TERM_LIFE"


def _simulate(index):
    return simulate_with({"lines": {LINE: {"severity": {"sum_insured_index": index}}}})


def _payments(sim):
    """Per non-nil claim of the line: paid amount, sum insured at base prices and at start,
    price factor at policy start, occurrence and payment, and the origin year."""
    w, p, market = sim.world, sim.policies, sim.market
    claims = np.flatnonzero((w.c_line == LINE) & ~w.c_nil)
    assert len(claims) >= 10
    first = {}  # one payment per claim for this line
    for i, c in enumerate(w.p_claim):
        first.setdefault(int(c), i)
    rows = np.array([first[int(c)] for c in claims])
    assert len(set(w.p_claim[rows])) == len(claims)
    policy = w.c_policy[claims]
    start = p.start[policy]
    return {
        "paid": w.p_amount[rows],
        "sum_start": p.sum_insured[policy],
        "sum_base": p.sum_insured[policy] / market.price_factor(start),
        "factor_start": market.price_factor(start),
        "factor_occurrence": market.price_factor(w.c_occ[claims]),
        "factor_payment": market.price_factor(w.p_day[rows]),
        "origin": year_of(w.c_occ[claims]),
        "claims": claims,
    }


def test_the_baseline_declares_an_index_on_occurrence_for_the_sum_insured_line():
    index = load_scenario("baseline").lines[LINE].severity.sum_insured_index
    assert index is not None and index.by == "occurrence" and index.prices


def test_a_declared_index_of_zero_gives_the_sum_insured_at_base_prices(baseline):
    sim = _simulate({"by": "occurrence", "prices": False})
    d = _payments(sim)
    # the claim is the sum insured at base-date prices, whatever the year: no trend by origin
    assert d["paid"] == pytest.approx(d["sum_base"], abs=0.01)
    by_origin = (
        pl.DataFrame({"origin": d["origin"], "ratio": d["paid"] / d["sum_base"]})
        .group_by("origin")
        .agg(pl.col("ratio").mean())
    )
    assert by_origin["ratio"].to_numpy() == pytest.approx(1.0, abs=1e-6)
    truth = sim.truth["inflation"][f"claims_index_{LINE}"]
    assert truth.to_numpy() == pytest.approx(1.0)  # superimposed inflation is 0 too


def test_a_declared_price_index_on_occurrence_gives_the_calendar_year_pattern():
    sim = _simulate({"by": "occurrence", "prices": True})
    d = _payments(sim)
    assert d["paid"] / d["sum_base"] == pytest.approx(d["factor_occurrence"], rel=1e-6)
    # not the price level of the start: a policy that started in 2016 and lost in 2017 pays 2017
    assert not np.allclose(d["paid"] / d["sum_base"], d["factor_start"], rtol=1e-3)
    truth = sim.truth["inflation"]
    assert truth[f"claims_index_{LINE}"].to_numpy() == pytest.approx(
        truth["cpi"].to_numpy() / 100.0, rel=1e-9
    )


def test_a_declared_index_on_settlement_follows_the_payment_day():
    sim = _simulate({"by": "settlement", "prices": True})
    d = _payments(sim)
    assert d["paid"] / d["sum_base"] == pytest.approx(d["factor_payment"], rel=1e-6)


def test_without_a_declaration_the_claim_is_tied_to_the_prices_of_the_policy_start():
    sim = _simulate(None)
    d = _payments(sim)
    assert d["paid"] == pytest.approx(d["sum_start"], abs=0.01)
    assert d["paid"] / d["sum_base"] == pytest.approx(d["factor_start"], rel=1e-6)
    truth = sim.truth["inflation"]
    assert truth[f"claims_index_{LINE}"].to_numpy() == pytest.approx(1.0)  # flat after the loss
    row = claim_size_index(sim.scenario).filter(pl.col("line") == LINE)
    assert row["index_day"][0] == "policy_start"


def test_the_truth_states_the_index_day_of_every_line(baseline):
    table = claim_size_index(baseline.scenario)
    assert set(table["line"]) == set(baseline.scenario.lines)
    by_line = dict(zip(table["line"], table["index_day"], strict=True))
    assert by_line[LINE] == "occurrence"
    assert by_line["MOTOR_TPL"] == "payment" and by_line["PROPERTY"] == "payment"


def test_the_index_is_refused_on_a_line_that_is_not_a_sum_insured_line():
    with pytest.raises(ValueError, match="sum_insured_index"):
        simulate_with(
            {"lines": {"MOTOR_TPL": {"severity": {"sum_insured_index": {"by": "occurrence"}}}}}
        )


def test_the_reserve_of_an_occurrence_indexed_claim_does_not_move_with_the_payment_day():
    sim = _simulate({"by": "occurrence", "prices": True})
    w = sim.world
    claims = np.flatnonzero((w.c_line == LINE) & ~w.c_nil)[:20]
    later = np.minimum(w.c_occ[claims] + 400, to_day(sim.scenario.meta.valuation.last))
    assert w.index_for(claims, w.c_occ[claims]) == pytest.approx(w.index_for(claims, later))
