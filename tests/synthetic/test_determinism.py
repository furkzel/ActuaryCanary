"""Every random draw descends from one seed: same seed, same data; stages stay independent."""

import numpy as np
import polars as pl

from actuarycanary.synthetic.build import simulate
from tests.synthetic.conftest import simulate_with


def _same_tables(a, b) -> bool:
    for feed, sheets in a.frames.items():
        if not all(sheets[k].equals(b.frames[feed][k]) for k in sheets):
            return False
    return all(a.truth[k].equals(b.truth[k]) for k in a.truth)


def test_the_same_seed_gives_the_same_tables_and_truth(baseline):
    assert _same_tables(baseline, simulate("baseline", "tiny"))


def test_another_seed_gives_other_data(baseline):
    other = simulate_with({"meta": {"seed": 1}})
    assert not other.frames["claims"]["claims"].equals(baseline.frames["claims"]["claims"])
    assert (
        other.truth["ultimates"]["ultimate_gross"].sum()
        != baseline.truth["ultimates"]["ultimate_gross"].sum()
    )


def test_changing_one_line_leaves_the_others_untouched(baseline):
    """Streams are named per stage and line, so a new frequency for third-party liability
    moves nothing about own damage."""
    changed = simulate_with({"lines": {"MOTOR_TPL": {"frequency": {"per_exposure_year": 0.2}}}})

    def own_damage(sim):
        w = sim.world
        mine = w.c_line == "MOTOR_OD"
        return np.column_stack([w.c_occ[mine], w.c_rep[mine], w.c_e0[mine]]), w.c_cost[mine]

    (times_a, cost_a), (times_b, cost_b) = own_damage(baseline), own_damage(changed)
    assert (times_a == times_b).all() and (cost_a == cost_b).all()
    assert len(changed.world) > len(baseline.world)
    assert (baseline.policies.premium == changed.policies.premium).all()


def test_the_market_does_not_depend_on_the_portfolio_size(baseline):
    other = simulate_with({"sizes": {"tiny": {"portfolio_scale": 0.004}}})
    assert (other.market.cpi == baseline.market.cpi).all()
    assert (other.market.fx["USD"] == baseline.market.fx["USD"]).all()
    assert other.truth["inflation"].equals(baseline.truth["inflation"])


def test_the_resolved_truth_keeps_the_scenario_name(baseline):
    assert baseline.scenario.name == "baseline" and baseline.size_name == "tiny"
    assert baseline.truth["ultimates"].schema["line"] == pl.String
