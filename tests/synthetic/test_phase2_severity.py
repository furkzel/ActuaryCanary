"""The true severity distribution of each line, for the extreme-value methods."""

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.claims import REGULAR
from actuarycanary.synthetic.draws import Streams, draw
from actuarycanary.synthetic.scenario import Line
from actuarycanary.synthetic.severity_truth import (
    LEVELS,
    cdf,
    mean,
    quantile,
    survival,
)
from tests.synthetic.conftest import NO_FAULTS, simulate_named


def _sample(line: Line, n: int, seed: int) -> np.ndarray:
    """Costs at base-date prices drawn by the rule of claims.py, regular claims only."""
    rng = Streams(seed).get("check", "severity")
    body = draw(line.severity.body, rng, n)
    tail = line.severity.tail
    if tail is not None:
        in_tail = rng.random(n) < tail.probability
        pareto = tail.threshold * (1.0 - rng.random(n)) ** (-1.0 / tail.alpha)
        body = np.where(in_tail, pareto, body)
    if line.litigation is not None:
        litigated = rng.random(n) < line.litigation.probability
        body = body * np.where(litigated, line.litigation.severity_multiplier, 1.0)
    return body


def test_the_quantiles_invert_the_distribution_function(clean_baseline):
    truth = clean_baseline.phase2.truth["severity_truth"]
    for row in truth.iter_rows(named=True):
        line = clean_baseline.scenario.lines[row["line"]]
        for p in LEVELS:
            x = row[f"quantile_{str(p).replace('.', '_')}"]
            assert abs(float(cdf(line, np.array([x]))[0]) - p) < 1e-9
    assert (
        cdf(line, np.array([1.0, 1e3, 1e9])) + survival(line, np.array([1.0, 1e3, 1e9]))
    ).tolist() == [1.0, 1.0, 1.0]


def test_the_tail_parameters_are_those_of_the_scenario(clean_baseline):
    truth = clean_baseline.phase2.truth["severity_truth"]
    assert set(truth["line"]) == {"MOTOR_OD", "MOTOR_TPL", "PROPERTY"}  # the life line has no tail
    for row in truth.iter_rows(named=True):
        tail = clean_baseline.scenario.lines[row["line"]].severity.tail
        assert tail is not None
        assert row["tail_alpha"] == tail.alpha and row["tail_threshold"] == tail.threshold
        assert row["tail_xi"] == pytest.approx(1.0 / tail.alpha)
        assert row["tail_gpd_sigma_at_threshold"] == pytest.approx(tail.threshold / tail.alpha)
        assert 0.9 < row["tail_start_probability"] < 1.0
    tpl = truth.filter(pl.col("line") == "MOTOR_TPL").row(0, named=True)
    assert tpl["litigation_multiplier"] == 2.5 and tpl["litigation_probability"] == 0.08


def test_the_mixture_matches_a_sample_drawn_by_the_rule_of_the_generator(clean_baseline):
    """The share of a sample below each true quantile is the level, within four binomial errors
    (a quantile of the sample itself is unstable where the distribution function is flat, as
    it is just below the tail threshold of PROPERTY)."""
    truth = clean_baseline.phase2.truth["severity_truth"]
    n = 400_000
    for row in truth.iter_rows(named=True):
        line = clean_baseline.scenario.lines[row["line"]]
        sample = _sample(line, n, seed=11)
        for p in LEVELS:
            below = float((sample <= row[f"quantile_{str(p).replace('.', '_')}"]).mean())
            assert abs(below - p) < 4 * (p * (1 - p) / n) ** 0.5, (row["line"], p)
        if line.severity.tail is not None and line.severity.tail.alpha > 2.0:
            assert abs(sample.mean() / mean(line) - 1.0) < 0.05, row["line"]


def test_the_mean_excess_over_a_threshold_matches_a_sample(clean_baseline):
    excess = clean_baseline.phase2.truth["severity_tail_truth"]
    for row in excess.filter(pl.col("probability_level") == 0.95).iter_rows(named=True):
        line = clean_baseline.scenario.lines[row["line"]]
        sample = _sample(line, 600_000, seed=12)
        over = sample[sample > row["threshold"]] - row["threshold"]
        assert abs(over.mean() / row["mean_excess"] - 1.0) < 0.12, row["line"]
    heavy = excess.filter(pl.col("line") == "PROPERTY").sort("probability_level")
    assert heavy["mean_excess"].to_list() == sorted(heavy["mean_excess"].to_list())  # heavy tail


@pytest.mark.slow
def test_the_claims_of_the_generator_follow_the_true_distribution():
    """Costs of regular claims of a bigger book against the true distribution function."""
    sim = simulate_named("baseline", {**NO_FAULTS, "sizes": {"tiny": {"portfolio_scale": 0.05}}})
    world = sim.world
    line = sim.scenario.lines["MOTOR_TPL"]
    keep = (world.c_line == "MOTOR_TPL") & (world.c_kind == REGULAR) & (world.c_currency == "TRY")
    cost = world.c_cost[keep]
    assert len(cost) > 1_000
    for p in (0.5, 0.9, 0.95):
        x = quantile(line, p)
        below = float((cost <= x).mean())
        assert abs(below - p) < 4 * (p * (1 - p) / len(cost)) ** 0.5, p
