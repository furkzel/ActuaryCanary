"""MT06 Mack standard error and the lognormal range: benchmarks, the hand-computed lognormal
step, failure modes, and the coverage of the 95th percentile: a calibration on triangles from
Mack's own model (with a tolerance) and on the synthetic baseline (information only)."""

import math
import os

import numpy as np
import polars as pl
import pytest

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.mack import (
    LOGNORMAL_LABEL,
    SELECTED_LABEL,
    Mack,
    applied_to_selected,
    lognormal_range,
    mack,
)
from tests.benchmarks.load import benchmark_names, load_benchmark
from tests.methods.helpers import HAND, array

BENCHMARK_RTOL = 1e-6  # MT06 benchmark tolerance
FIXTURE_RTOL = 1e-9
# standard normal quantiles, from tables
Z = {0.5: 0.0, 0.75: 0.6744897501960817, 0.9: 1.2815515655446004, 0.95: 1.6448536269514722,
     0.99: 2.3263478740408408, 0.995: 2.5758293035489004}  # fmt: skip


def _run(cumulative: np.ndarray) -> Mack:
    result = mack(cumulative)
    assert isinstance(result, Mack)
    return result


@pytest.mark.parametrize("name", benchmark_names())
def test_benchmark_standard_errors(name: str) -> None:
    benchmark = load_benchmark(name)
    expected = benchmark["expected"]
    result = _run(array(benchmark["triangle"]))
    np.testing.assert_allclose(
        result.standard_error, expected["mack_std_err"], rtol=BENCHMARK_RTOL, atol=1e-9
    )
    assert result.total_standard_error == pytest.approx(
        expected["total"]["mack_std_err"], rel=BENCHMARK_RTOL
    )
    assert result.total_reserve == pytest.approx(expected["total"]["ibnr"], rel=1e-9)
    assert result.extrapolated.tolist() == [False] * 8 + [True]  # the last column (MT06)


def test_lognormal_step_for_reserve_100_and_standard_error_20() -> None:
    sigma2 = math.log(1 + (20 / 100) ** 2)
    sigma, mu = math.sqrt(sigma2), math.log(100) - sigma2 / 2
    found = lognormal_range(100.0, 20.0)
    assert found is not None
    assert found.mu == pytest.approx(mu, rel=FIXTURE_RTOL)
    assert found.sigma == pytest.approx(sigma, rel=FIXTURE_RTOL)
    for p, z in Z.items():
        assert found.percentiles[p] == pytest.approx(math.exp(mu + sigma * z), rel=FIXTURE_RTOL)
    assert found.value_at_risk == pytest.approx(math.exp(mu + sigma * Z[0.995]), rel=FIXTURE_RTOL)
    phi = 0.5 * (1 + math.erf((sigma - Z[0.99]) / math.sqrt(2)))
    assert found.tail_value_at_risk == pytest.approx(
        math.exp(mu + sigma2 / 2) * phi / 0.01, rel=FIXTURE_RTOL
    )
    assert found.label == LOGNORMAL_LABEL
    assert found.percentiles[0.5] < 100 < found.tail_value_at_risk  # the median is below the mean


def test_ranges_per_origin_and_total_skip_a_zero_reserve() -> None:
    result = _run(array(load_benchmark("raa")["triangle"]))
    per_origin, total = result.ranges()
    assert per_origin[0] is None  # the fully developed origin has no reserve
    assert all(r is not None for r in per_origin[1:])
    assert total is not None and total.reserve == pytest.approx(result.total_reserve)
    assert result.total_coefficient_of_variation == pytest.approx(
        26909.01115564366 / 52135.228261210155
    )


def test_coefficient_of_variation_applied_to_a_selected_reserve_is_labelled() -> None:
    selected = applied_to_selected(0.2, 100.0)
    assert selected.standard_error == pytest.approx(20.0)
    assert selected.label == SELECTED_LABEL
    assert selected.range is not None and selected.range.label == LOGNORMAL_LABEL
    assert applied_to_selected(0.2, -5.0).range is None


def test_too_few_columns_with_variance_is_not_run() -> None:
    # 4 x 4: sigma estimable in columns 0 and 1 only
    assert mack(array(HAND["paid"])) == Skipped("MT06", "too few link ratios to estimate variance")


def test_chain_ladder_failure_is_passed_on() -> None:
    result = mack(np.array([[1.0, 2.0], [1.0, np.nan]]))
    assert result == Skipped("MT06", "chain ladder needs at least 3 origin periods")


def test_residuals_are_standardised_link_ratio_deviations() -> None:
    result = _run(array(load_benchmark("genins")["triangle"]))
    chain = result.chain
    i, j = 3, 1
    expected = (
        (chain.link_ratios[i, j] - chain.factors[j])
        * math.sqrt(load_benchmark("genins")["triangle"]["values"][i][j] or 0)
        / math.sqrt(result.sigma_squared[j])
    )
    assert result.residuals[i, j] == pytest.approx(expected, rel=1e-12)
    assert np.isnan(result.residuals[9]).all()  # the newest origin has no link ratio


# Calibration (spec MT06 1.1.0, record 0062): triangles drawn from Mack's own model with the
# GenIns parameters. Link ratios are gamma with mean f(j) C(i,j) for C(i,j+1) and variance
# sigma^2(j) C(i,j); the first column is the one of GenIns. Run with ACTUARYCANARY_MONTE_CARLO=1.
CALIBRATION_RUNS = 2000
CALIBRATION_SEED = 20261022
COVERAGE_RANGE = (0.90, 0.99)  # MT06 tolerance
MONTE_CARLO = pytest.mark.skipif(
    os.environ.get("ACTUARYCANARY_MONTE_CARLO") != "1",
    reason="Monte Carlo coverage test; set ACTUARYCANARY_MONTE_CARLO=1",
)


def _genins_model() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """First column, f(j) and sigma^2(j) of GenIns under Mack's estimators."""
    triangle = array(load_benchmark("genins")["triangle"])
    fit = _run(triangle)
    return triangle[:, 0], fit.chain.factors, fit.sigma_squared


def _draw_triangle(
    rng: np.random.Generator, first: np.ndarray, f: np.ndarray, sigma2: np.ndarray
) -> np.ndarray:
    """One complete cumulative triangle of Mack's model (origins x development columns)."""
    n = len(first)
    full = np.empty((n, n))
    full[:, 0] = first
    for j in range(n - 1):
        mean = f[j] * full[:, j]
        full[:, j + 1] = rng.gamma(mean * f[j] / sigma2[j], sigma2[j] / f[j])
    return full


def _observed(full: np.ndarray) -> np.ndarray:
    """The upper triangle of a complete one: origin i is seen up to column n - 1 - i."""
    n = len(full)
    return np.where(np.arange(n)[None, :] <= (n - 1 - np.arange(n))[:, None], full, np.nan)


def test_drawn_triangles_follow_the_model_in_mean_and_variance() -> None:
    first, f, sigma2 = _genins_model()
    rng = np.random.default_rng(CALIBRATION_SEED)
    draws = np.array([_draw_triangle(rng, first, f, sigma2) for _ in range(500)])
    assert (draws[:, :, 0] == first).all()
    ratio_mean = (draws[:, 3, 4] / draws[:, 3, 3]).mean()
    assert ratio_mean == pytest.approx(f[3], rel=0.02)
    scaled_var = ((draws[:, 3, 4] - f[3] * draws[:, 3, 3]) ** 2 / draws[:, 3, 3]).mean()
    assert scaled_var == pytest.approx(sigma2[3], rel=0.25)
    seen = _observed(draws[0])
    assert np.isnan(seen).sum() == 45 and np.isnan(seen[9, 1]) and not np.isnan(seen[9, 0])


@pytest.mark.slow
@MONTE_CARLO
def test_ground_truth_calibration_on_triangles_from_mack_model() -> None:
    first, f, sigma2 = _genins_model()
    rng = np.random.default_rng(CALIBRATION_SEED)
    hits = []
    for _ in range(CALIBRATION_RUNS):
        full = _draw_triangle(rng, first, f, sigma2)
        seen = _observed(full)
        result = _run(seen)
        _, total = result.ranges()
        assert total is not None
        true_reserve = float(full[:, -1].sum() - np.nanmax(seen, axis=1).sum())
        hits.append(true_reserve <= total.percentiles[0.95])
    coverage = float(np.mean(hits))
    print(
        f"coverage of the 95th percentile over {CALIBRATION_RUNS} Mack-model runs: {coverage:.3f}"
    )
    low, high = COVERAGE_RANGE
    assert low <= coverage <= high, coverage


# Information, no tolerance (records 0045, 0062): 200 simulations of the baseline at 2 per cent of
# its portfolio (about 0.5 s each). Calendar-year inflation, development after ten years and the
# 2023 earthquake break the independence of origins, so the coverage is below the nominal 95 per
# cent on most lines.
SYNTHETIC_RUNS = 200
SYNTHETIC_SCALE = 0.02


def _synthetic_coverage() -> dict[str, float]:
    from actuarycanary.structures.triangles import TriangleSettings, build_triangles
    from actuarycanary.synthetic.build import simulate
    from actuarycanary.synthetic.scenario import SizeSpec, load_scenario

    base = load_scenario("baseline")
    hits: dict[str, list[bool]] = {}
    for k in range(SYNTHETIC_RUNS):
        scenario = base.model_copy(
            update={"meta": base.meta.model_copy(update={"seed": base.meta.seed + k + 1})}
        )
        sim = simulate(scenario, SizeSpec(portfolio_scale=SYNTHETIC_SCALE))
        truth = sim.truth["ultimates"]
        rates = dict(truth.select("currency", "fx_cutoff_rate").unique().iter_rows())
        valuations = sim.clean["claim_valuations"].with_row_index(SOURCE_ROW)
        triangles = build_triangles(
            valuations, sim.clean["claims"], TriangleSettings(), rates, "TRY", measures=("paid",)
        )
        reserves = truth.group_by("line").agg(
            ((pl.col("ultimate_gross") - pl.col("paid_at_cutoff")) * pl.col("fx_cutoff_rate"))
            .sum()
            .alias("reserve")
        )
        for group in triangles.groups:
            result = mack(triangles.get("paid", group).cumulative)
            if not isinstance(result, Mack):
                continue
            _, total = result.ranges()
            if total is None:
                continue
            true = reserves.filter(pl.col("line") == group[1])["reserve"][0]
            hits.setdefault(group[1], []).append(bool(true <= total.percentiles[0.95]))
    return {line: float(np.mean(h)) for line, h in sorted(hits.items())}


@pytest.mark.slow
@MONTE_CARLO
def test_synthetic_baseline_coverage_is_reported_as_information() -> None:
    coverage = _synthetic_coverage()
    print(f"coverage of the 95th percentile on the synthetic baseline, per line: {coverage}")
    assert coverage and all(0.0 <= c <= 1.0 for c in coverage.values())
