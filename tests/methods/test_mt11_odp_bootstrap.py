"""MT11 over-dispersed Poisson bootstrap: 4 x 4 fixture by hand, deterministic benchmark rows,
the simulation criteria of decision 0282, properties, failure modes and the calibration on
triangles drawn from the model (Monte Carlo, behind ACTUARYCANARY_MONTE_CARLO=1)."""

import math
import os

import numpy as np
import polars as pl
import pytest

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.mack import Mack, mack
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, Process, Scale, odp_bootstrap, summary
from actuarycanary.methods.seeding import generator
from tests.methods.helpers import HAND, array, fitted
from tests.methods.tier_b import reference, table, triangle, value

MONTE_CARLO = pytest.mark.skipif(
    os.environ.get("ACTUARYCANARY_MONTE_CARLO") != "1",
    reason="Monte Carlo test; set ACTUARYCANARY_MONTE_CARLO=1",
)
MEAN_TOLERANCE = 0.05  # decision 0282
SIMS = 2_000  # enough for the properties; the benchmark uses the 10,000 of the spec


def _run(cumulative, *args, **options) -> OdpBootstrap:
    result = odp_bootstrap(cumulative, *args, **options)
    assert isinstance(result, OdpBootstrap)
    return result


def test_hand_fixture_fitted_values_residuals_scale_and_pool() -> None:
    cumulative = array(HAND["paid"])
    x = [[90.0, 80.0, 30.0, 20.0], [110.0, 100.0, 46.0], [100.0, 90.0], [130.0]]
    c = [[sum(row[: j + 1]) for j in range(len(row))] for row in x]
    f = [
        sum(c[i][j + 1] for i in range(3 - j)) / sum(c[i][j] for i in range(3 - j))
        for j in range(3)
    ]
    fitted_cum = []
    for row in c:
        back = [row[-1]]
        for j in range(len(row) - 2, -1, -1):
            back.insert(0, back[0] / f[j])
        fitted_cum.append(back)
    mu = [[r[0]] + [r[j] - r[j - 1] for j in range(1, len(r))] for r in fitted_cum]
    r = [[(x[i][j] - mu[i][j]) / math.sqrt(mu[i][j]) for j in range(len(x[i]))] for i in range(4)]
    n, p = 10, 7
    phi = sum(v * v for row in r for v in row) / (n - p)

    result = _run(cumulative, n_simulations=10, min_origins=4)
    for i in range(4):
        for j in range(4 - i):
            assert result.fitted[i, j] == pytest.approx(mu[i][j], rel=1e-12)
            assert result.unscaled_residuals[i, j] == pytest.approx(r[i][j], rel=1e-12, abs=1e-12)
            assert result.adjusted_residuals[i, j] == pytest.approx(
                r[i][j] * math.sqrt(n / (n - p)), rel=1e-12, abs=1e-12
            )
    assert result.scale_parameter == pytest.approx(phi, rel=1e-12)
    assert result.degrees_of_freedom == 3
    # the cells fitted exactly: the first column of the latest origin, the last of the oldest
    assert abs(r[3][0]) < 1e-12 and abs(r[0][3]) < 1e-12
    assert not result.in_pool[3, 0] and not result.in_pool[0, 3] and result.in_pool.sum() == 8
    assert result.pool.mean() == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_benchmark_deterministic_rows(name: str) -> None:
    ref = f"MT11-odp-bootstrap-{name}"
    tri, origins, ages = triangle(ref)
    result = _run(tri, n_simulations=SIMS)
    assert result.scale_parameter == pytest.approx(
        value(ref, "deterministic", "scale_parameter_phi"), rel=1e-9
    )
    assert result.chain.reserve.sum() == pytest.approx(
        value(ref, "deterministic", "chain_ladder_reserve"), rel=1e-9
    )
    assert np.nansum(result.adjusted_residuals**2) == pytest.approx(
        value(ref, "deterministic", "adjusted_residual_sum_of_squares"), rel=1e-9
    )
    rows = {(r["origin"], int(r["age"])): r for r in table(ref, "residuals.csv")}
    frame = result.residual_table(origins, ages)
    assert frame.height == len(rows) == 55
    for row in frame.iter_rows(named=True):
        frozen = rows[(row["origin"], row["age"])]
        assert row["unscaled"] == pytest.approx(
            float(frozen["unscaled_residual"]), rel=1e-9, abs=1e-9
        )
        assert row["adjusted"] == pytest.approx(
            float(frozen["adjusted_residual"]), rel=1e-9, abs=1e-9
        )


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_benchmark_simulation_mean_and_information(name: str) -> None:
    """Pass: the mean within 5 per cent of the chain ladder (decision 0282). The percentiles of
    the re-frozen reference are printed beside MT11's as information."""
    ref = f"MT11-odp-bootstrap-{name}"
    tri, _, _ = triangle(ref)
    manifest = reference(ref)["manifest"]
    result = _run(tri, seed=manifest["seed"], n_simulations=manifest["n_simulations"])
    _, total = result.summary()
    reserve = value(ref, "deterministic", "chain_ladder_reserve")
    assert abs(total.mean / reserve - 1) <= MEAN_TOLERANCE
    q = "simulation_with_process_error_total_reserve"
    ours = {"mean": total.mean, "sd": total.standard_deviation} | {
        f"p{100 * p:g}": total.percentiles[p] for p in (0.5, 0.75, 0.95, 0.995)
    }
    shown = {
        k: (round(v), round(value(ref, q, k)), f"{v / value(ref, q, k) - 1:+.4f}")
        for k, v in ours.items()
    }
    print(
        f"{name} MT11 against the re-frozen reference (information): {shown}; "
        f"bias {result.bias:+.4f}"
    )


def test_same_seed_same_output_and_streams_per_group() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    a = _run(tri, generator(7, "NON_LIFE", "MOTOR_TPL"), n_simulations=SIMS)
    b = _run(tri, generator(7, "NON_LIFE", "MOTOR_TPL"), n_simulations=SIMS)
    other = _run(tri, generator(7, "NON_LIFE", "PROPERTY"), n_simulations=SIMS)
    np.testing.assert_array_equal(a.reserves, b.reserves)
    np.testing.assert_array_equal(a.cash_flows, b.cash_flows)
    assert not np.array_equal(a.reserves, other.reserves)
    plain = _run(tri, seed=7, n_simulations=SIMS)
    np.testing.assert_array_equal(
        plain.reserves, _run(tri, generator(7), n_simulations=SIMS).reserves
    )
    assert plain.seed == 7


def test_scaling_the_triangle_scales_every_simulated_reserve() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-genins")
    base = _run(tri, seed=3, n_simulations=SIMS)
    scaled = _run(tri * 2.5, seed=3, n_simulations=SIMS)
    np.testing.assert_allclose(scaled.reserves, base.reserves * 2.5, rtol=1e-9)
    np.testing.assert_allclose(scaled.scale_parameter, base.scale_parameter * 2.5, rtol=1e-12)


def test_triangle_built_from_rows_in_any_order_gives_the_same_draws() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    rows = pl.DataFrame(
        [(i, j, float(tri[i, j])) for i in range(10) for j in range(10) if np.isfinite(tri[i, j])],
        schema=["origin", "dev", "value"], orient="row",
    )  # fmt: skip

    def built(frame: pl.DataFrame) -> np.ndarray:
        out = np.full((10, 10), np.nan)
        for i, j, v in frame.iter_rows():
            out[i, j] = v
        return out

    shuffled = rows.sample(fraction=1.0, shuffle=True, seed=11)
    first = _run(built(rows), seed=5, n_simulations=500)
    second = _run(built(shuffled), seed=5, n_simulations=500)
    np.testing.assert_array_equal(first.reserves, second.reserves)


def test_outputs_summary_cash_flows_and_diagnostics() -> None:
    tri, origins, _ = triangle("MT11-odp-bootstrap-raa")
    result = _run(tri, seed=1, n_simulations=SIMS)
    per_origin, total = result.summary()
    assert len(per_origin) == 10 and per_origin[0].mean == 0
    assert total.percentiles[0.5] < total.percentiles[0.95] <= total.value_at_risk
    assert total.tail_value_at_risk >= total.percentiles[0.99]
    np.testing.assert_allclose(result.cash_flows.sum(axis=1), result.total, rtol=1e-9)
    assert result.cash_flows.shape == (SIMS, 9)
    assert [s.mean for s in result.cash_flow_summary()][0] > 0
    frame = result.distribution_frame(origins)
    assert frame.columns == ["simulation", *origins, "total"] and frame.height == SIMS
    counts, edges = result.histogram()
    assert counts.sum() == SIMS and len(edges) == 51
    fit = mack(tri)
    assert isinstance(fit, Mack)
    beside = result.against_mack(fit)
    assert beside["mack_reserve"] == pytest.approx(fit.total_reserve)
    assert {"bootstrap_p0.95", "mack_p0.95"} <= set(beside)
    single = summary(np.arange(1.0, 101.0), percentiles=(0.5,), var_level=0.9, tvar_level=0.9)
    assert single.value_at_risk == pytest.approx(
        90.1
    ) and single.tail_value_at_risk == pytest.approx(95.5)


def test_odp_process_and_a_tail() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    odp = _run(tri, seed=2, n_simulations=SIMS, process_distribution=Process.ODP)
    multiples = odp.reserves / odp.scale_parameter  # phi times whole numbers, signs restored
    np.testing.assert_allclose(multiples, np.round(multiples), atol=1e-6)
    no_tail = _run(tri, seed=2, n_simulations=SIMS)
    tail = _run(tri, seed=2, n_simulations=SIMS, tail_factor=1.05)
    assert tail.cash_flows.shape[1] == 10  # the tail of the oldest origin falls after its last age
    assert tail.total.mean() > no_tail.total.mean()
    assert tail.reserves[:, 0].min() > 0  # the oldest origin now has a tail


def test_failure_modes() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    assert odp_bootstrap(tri[:4, :4]) == Skipped(
        "MT11", "the bootstrap needs a chain ladder on at least 5 origin periods"
    )
    found = odp_bootstrap(tri, scale=Scale.BY_DEVELOPMENT)
    assert isinstance(found, Skipped) and "by_development is not built" in found.reason
    negative = tri.copy()
    negative[:, 9] = negative[:, 8] - 100  # the last column of increments sums below zero
    found = odp_bootstrap(negative)
    assert isinstance(found, Skipped) and "column 9" in found.reason
    small = np.array([[90.0, 170.0, 200.0], [110.0, 210.0, np.nan], [100.0, np.nan, np.nan]])
    assert odp_bootstrap(small, min_origins=3) == Skipped(
        "MT11", "too few cells to estimate the scale parameter"
    )
    with pytest.raises(ValueError, match="at least 2"):
        odp_bootstrap(tri, n_simulations=1)


def test_many_negative_totals_give_a_warning() -> None:
    # short tail: nearly everything paid in the first column, small increments of both signs later
    increments = np.array(
        [[1000, 30, -20, 15, 5, 2], [1100, -25, 40, -10, 6, 0], [950, 45, -30, 12, 0, 0],
         [1050, -35, 25, 0, 0, 0], [980, 50, 0, 0, 0, 0], [1020, 0, 0, 0, 0, 0]], dtype=float
    )  # fmt: skip
    cumulative = np.cumsum(increments, axis=1)
    cumulative[np.add.outer(np.arange(6), np.arange(6)) > 5] = np.nan
    found = _run(cumulative, seed=1, n_simulations=SIMS)
    assert (found.total < 0).mean() > 0.01
    assert [d.code for d in found.diagnostics] == ["NEGATIVE_TOTAL_RESERVE"]


# Calibration (spec MT11, decision 0282): triangles drawn from the over-dispersed Poisson model
# with the GenIns row and column parameters and scale, 1,000 triangles, 2,000 simulations each.
CALIBRATION_RUNS = 1_000
CALIBRATION_SIMS = 2_000
CALIBRATION_SEED = 20261025
COVERAGE_RANGE = (0.90, 0.99)


def _genins_model() -> tuple[np.ndarray, float]:
    """Expected incremental cells (full square) and phi of the model fitted to GenIns."""
    tri, _, _ = triangle("MT11-odp-bootstrap-genins")
    chain = fitted(tri)
    pattern = np.diff(np.concatenate([[0.0], 1 / chain.cdf]))
    means = np.outer(chain.ultimate, pattern)
    phi = _run(tri, n_simulations=10).scale_parameter
    return means, phi


@pytest.mark.slow
@MONTE_CARLO
def test_calibration_on_triangles_drawn_from_the_model() -> None:
    means, phi = _genins_model()
    n = len(means)
    upper = np.add.outer(np.arange(n), np.arange(n)) <= n - 1
    rng = np.random.default_rng(CALIBRATION_SEED)
    hits = []
    for k in range(CALIBRATION_RUNS):
        cells = rng.gamma(means / phi, phi)
        observed = np.where(upper, np.cumsum(np.where(upper, cells, 0.0), axis=1), np.nan)
        result = odp_bootstrap(
            observed, generator(CALIBRATION_SEED, str(k)), n_simulations=CALIBRATION_SIMS
        )
        assert isinstance(result, OdpBootstrap)
        true_reserve = float(cells[~upper].sum())
        hits.append(true_reserve <= np.quantile(result.total, 0.95))
    coverage = float(np.mean(hits))
    print(
        f"MT11 coverage of the 95th percentile over {CALIBRATION_RUNS} model triangles: "
        f"{coverage:.3f}"
    )
    low, high = COVERAGE_RANGE
    assert low <= coverage <= high, coverage


SYNTHETIC_RUNS = 100
SYNTHETIC_SCALE = 0.02


@pytest.mark.slow
@MONTE_CARLO
def test_synthetic_baseline_coverage_beside_mack_is_information() -> None:
    from actuarycanary.io.excel import SOURCE_ROW
    from actuarycanary.structures.triangles import TriangleSettings, build_triangles
    from actuarycanary.synthetic.build import simulate
    from actuarycanary.synthetic.scenario import SizeSpec, load_scenario

    base = load_scenario("baseline")
    hits: dict[str, dict[str, list[bool]]] = {}
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
            cumulative = triangles.get("paid", group).cumulative
            true = reserves.filter(pl.col("line") == group[1])["reserve"][0]
            line = hits.setdefault(group[1], {"MT11": [], "MT06": []})
            boot = odp_bootstrap(cumulative, generator(k, *group), n_simulations=CALIBRATION_SIMS)
            if isinstance(boot, OdpBootstrap):
                line["MT11"].append(bool(true <= np.quantile(boot.total, 0.95)))
            fit = mack(cumulative)
            if isinstance(fit, Mack) and (total := fit.ranges()[1]) is not None:
                line["MT06"].append(bool(true <= total.percentiles[0.95]))
    coverage = {
        line: {m: round(float(np.mean(h)), 3) if h else None for m, h in by.items()}
        for line, by in sorted(hits.items())
    }
    print(f"coverage of the 95th percentile on the synthetic baseline, per line: {coverage}")
    assert coverage
