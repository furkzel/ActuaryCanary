"""MT11 1.2.0: trailing development columns whose incremental paid sums to zero or less are cut
before the fit (decision 0349). Two 5 x 5 hand fixtures, the property that appending an all-zero
column changes no simulated number, the columns that still stop the method, and the calibration on
triangles drawn from a short-tail model (Monte Carlo, behind ACTUARYCANARY_MONTE_CARLO=1)."""

import math
import os
import time

import numpy as np
import pytest

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, odp_bootstrap, trailing_cut
from actuarycanary.methods.seeding import generator
from tests.methods.helpers import fitted
from tests.methods.tier_b import triangle

MONTE_CARLO = pytest.mark.skipif(
    os.environ.get("ACTUARYCANARY_MONTE_CARLO") != "1",
    reason="Monte Carlo test; set ACTUARYCANARY_MONTE_CARLO=1",
)
SIMS = 500

# 5 x 5 incremental triangles, origins 0..4, the cells with i + j <= 4 observed.
ZERO_LAST_COLUMN = [
    [100.0, 60.0, 30.0, 10.0, 0.0],
    [110.0, 70.0, 25.0, 12.0],
    [105.0, 65.0, 28.0],
    [120.0, 80.0],
    [115.0],
]
NEGATIVE_LAST_TWO = [
    [100.0, 60.0, 30.0, -4.0, -3.0],
    [110.0, 70.0, 25.0, -2.0],
    [105.0, 65.0, 28.0],
    [120.0, 80.0],
    [115.0],
]


def _cumulative(increments: list[list[float]]) -> np.ndarray:
    out = np.full((len(increments), len(increments[0])), np.nan)
    for i, row in enumerate(increments):
        out[i, : len(row)] = np.cumsum(row)
    return out


def _hand(rows: list[list[float]]) -> dict:
    """Volume-weighted chain ladder, fitted increments, Pearson residuals and phi of a trapezoid
    of cumulative rows, in plain Python (the figures of the specification, step by step)."""
    n_dev = max(len(r) for r in rows)
    f = []
    for j in range(n_dev - 1):
        both = [r for r in rows if len(r) > j + 1]
        f.append(sum(r[j + 1] for r in both) / sum(r[j] for r in both))
    fitted_cum = []
    for row in rows:
        back = [row[-1]]
        for j in range(len(row) - 2, -1, -1):
            back.insert(0, back[0] / f[j])
        fitted_cum.append(back)
    mu = [[r[0]] + [r[j] - r[j - 1] for j in range(1, len(r))] for r in fitted_cum]
    x = [[r[0]] + [r[j] - r[j - 1] for j in range(1, len(r))] for r in rows]
    resid = [
        [(x[i][j] - mu[i][j]) / math.sqrt(mu[i][j]) for j in range(len(x[i]))]
        for i in range(len(rows))
    ]
    n = sum(len(r) for r in rows)
    p = len(rows) + n_dev - 1
    phi = sum(v * v for row in resid for v in row) / (n - p)
    reserve = []
    for row in rows:
        ult = row[-1]
        for j in range(len(row) - 1, n_dev - 1):
            ult *= f[j]
        reserve.append(ult - row[-1])
    return {"f": f, "mu": mu, "resid": resid, "n": n, "p": p, "phi": phi, "reserve": reserve}


def _run(cumulative: np.ndarray, *args, **options) -> OdpBootstrap:
    options.setdefault("n_simulations", SIMS)
    result = odp_bootstrap(cumulative, *args, **options)
    assert isinstance(result, OdpBootstrap), result
    return result


def _check_against_hand(result: OdpBootstrap, rows: list[list[float]]) -> dict:
    hand = _hand(rows)
    n = hand["n"]
    dof = n - hand["p"]
    for i, row in enumerate(rows):
        for j in range(len(row)):
            assert result.fitted[i, j] == pytest.approx(hand["mu"][i][j], rel=1e-12)
            assert result.unscaled_residuals[i, j] == pytest.approx(
                hand["resid"][i][j], rel=1e-12, abs=1e-12
            )
            assert result.adjusted_residuals[i, j] == pytest.approx(
                hand["resid"][i][j] * math.sqrt(n / dof), rel=1e-12, abs=1e-12
            )
    assert result.scale_parameter == pytest.approx(hand["phi"], rel=1e-12)
    assert result.degrees_of_freedom == dof
    np.testing.assert_allclose(result.chain.factors, hand["f"], rtol=1e-12)
    np.testing.assert_allclose(result.chain.reserve, hand["reserve"], rtol=1e-12, atol=1e-12)
    assert result.pool.mean() == pytest.approx(0, abs=1e-12)
    return hand


def test_last_column_zero_is_cut_and_the_fit_is_that_of_the_cut_triangle() -> None:
    result = _run(_cumulative(ZERO_LAST_COLUMN), min_origins=5)
    assert result.cut_columns == (4,) and result.columns_cut == 1
    assert result.fitted.shape == (5, 4) and result.reserves.shape == (SIMS, 5)
    rows = [list(np.cumsum(r)) for r in ZERO_LAST_COLUMN]
    rows[0] = rows[0][:4]  # the cut triangle: the oldest origin ends at column 3
    hand = _check_against_hand(result, rows)
    assert (hand["n"], hand["p"]) == (14, 8) and result.degrees_of_freedom == 6
    # only the single cell of the latest origin is fitted exactly; the pool has 13 cells
    assert result.in_pool.sum() == 13 and not result.in_pool[4, 0]
    # the chain ladder of the whole triangle has the factor 1 beyond the cut
    assert result.cut_reserve_difference == pytest.approx(0, abs=1e-9)
    assert result.full_chain_reserve == pytest.approx(float(result.chain.reserve.sum()), rel=1e-12)
    assert result.diagnostics == ()
    assert "development column 3" in result.cut_note((12, 24, 36, 48, 60))
    assert "(age 60)" in result.cut_note((12, 24, 36, 48, 60))


def test_last_two_columns_summing_below_zero_are_cut_and_the_difference_is_reported() -> None:
    cumulative = _cumulative(NEGATIVE_LAST_TWO)
    result = _run(cumulative, min_origins=5)
    assert result.cut_columns == (3, 4) and result.columns_cut == 2
    assert result.fitted.shape == (5, 3)
    rows = [list(np.cumsum(r)) for r in NEGATIVE_LAST_TWO]
    rows = [r[:3] for r in rows]
    hand = _check_against_hand(result, rows)
    assert (hand["n"], hand["p"]) == (12, 7) and result.degrees_of_freedom == 5
    # the chain ladder of the whole triangle, by hand: factors below 1 beyond the cut
    full = [list(np.cumsum(r)) for r in NEGATIVE_LAST_TWO]
    whole = _hand_full_reserve(full)
    assert result.full_chain_reserve == pytest.approx(whole, rel=1e-12)
    difference = sum(hand["reserve"]) - whole
    assert result.cut_reserve_difference == pytest.approx(difference, rel=1e-9)
    assert abs(difference) > 0.01 * whole
    assert [d.code for d in result.diagnostics] == ["CUT_RESERVE_DIFFERENCE"]
    assert result.diagnostics[0].value == pytest.approx(difference, rel=1e-9)


def _hand_full_reserve(rows: list[list[float]]) -> float:
    n_dev = max(len(r) for r in rows)
    f = []
    for j in range(n_dev - 1):
        both = [r for r in rows if len(r) > j + 1]
        f.append(sum(r[j + 1] for r in both) / sum(r[j] for r in both))
    total = 0.0
    for row in rows:
        ult = row[-1]
        for j in range(len(row) - 1, n_dev - 1):
            ult *= f[j]
        total += ult - row[-1]
    return total


def test_a_positive_column_before_a_negative_last_column_cuts_only_the_last() -> None:
    increments = [list(r) for r in ZERO_LAST_COLUMN]
    increments[0][4] = -5.0
    result = _run(_cumulative(increments), min_origins=5)
    assert result.cut_columns == (4,)
    rows = [list(np.cumsum(r)) for r in increments]
    rows[0] = rows[0][:4]
    _check_against_hand(result, rows)
    assert result.cut_reserve_difference != 0  # the factor beyond the cut is 1 - 5 / 200


def test_no_cut_means_no_cut_fields_and_the_old_numbers() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    result = _run(tri)
    assert result.cut_columns == () and result.columns_cut == 0
    assert result.cut_reserve_difference == 0 and result.cut_note((1,) * 10) == ""
    assert result.full_chain_reserve == pytest.approx(float(result.chain.reserve.sum()))


def _short_triangle() -> np.ndarray:
    """RAA cut to eight columns: ten origins, the oldest two with all eight."""
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    return tri[:, :8].copy()


@pytest.mark.parametrize("extra", [1, 2])
def test_appending_zero_increment_columns_changes_no_simulated_number(extra: int) -> None:
    base = _short_triangle()
    longer = base
    for _ in range(extra):  # a column with the previous cumulative: increments of exactly zero
        longer = np.hstack([longer, longer[:, [-1]]])
    assert np.isfinite(longer[0, -1]) and np.isnan(longer[9, -1])
    a = odp_bootstrap(base, generator(5, "A"), n_simulations=SIMS)
    b = odp_bootstrap(longer, generator(5, "A"), n_simulations=SIMS)
    assert isinstance(a, OdpBootstrap) and isinstance(b, OdpBootstrap)
    assert a.columns_cut == 0 and b.cut_columns == tuple(range(8, 8 + extra))
    np.testing.assert_array_equal(a.reserves, b.reserves)
    np.testing.assert_array_equal(a.cash_flows, b.cash_flows)
    np.testing.assert_array_equal(a.fitted, b.fitted)
    assert a.scale_parameter == b.scale_parameter
    assert b.cut_reserve_difference == pytest.approx(0, abs=1e-9)
    assert b.diagnostics == a.diagnostics


def test_appending_a_column_with_no_observed_cell_changes_no_simulated_number() -> None:
    base = _short_triangle()
    longer = np.hstack([base, np.full((10, 1), np.nan)])
    a = odp_bootstrap(base, generator(5, "A"), n_simulations=SIMS)
    b = odp_bootstrap(longer, generator(5, "A"), n_simulations=SIMS)
    assert isinstance(a, OdpBootstrap) and isinstance(b, OdpBootstrap)
    np.testing.assert_array_equal(a.reserves, b.reserves)
    assert b.cut_columns == (8,)


def test_a_cut_triangle_with_a_tail_keeps_the_tail_after_its_last_kept_column() -> None:
    base = _short_triangle()
    longer = np.hstack([base, base[:, [-1]]])
    a = odp_bootstrap(base, generator(5, "A"), n_simulations=SIMS, tail_factor=1.03)
    b = odp_bootstrap(longer, generator(5, "A"), n_simulations=SIMS, tail_factor=1.03)
    assert isinstance(a, OdpBootstrap) and isinstance(b, OdpBootstrap)
    np.testing.assert_array_equal(a.reserves, b.reserves)
    np.testing.assert_array_equal(a.cash_flows, b.cash_flows)


def test_a_non_positive_column_that_is_not_trailing_still_stops_the_method() -> None:
    tri, _, _ = triangle("MT11-odp-bootstrap-raa")
    increments = tri.copy()
    increments[:, 1:] = tri[:, 1:] - tri[:, :-1]
    increments[:, 3] = np.where(np.isfinite(tri[:, 3]), 0.0, np.nan)  # sums to zero
    flat = np.cumsum(np.nan_to_num(increments), axis=1)
    flat[np.isnan(tri)] = np.nan
    found = odp_bootstrap(flat)
    assert isinstance(found, Skipped) and found.method == "MT11"
    assert "development column 3 sums to zero or less" in found.reason
    assert "not a trailing column" in found.reason
    increments[:, 3] = np.where(np.isfinite(tri[:, 3]), -10.0, np.nan)  # sums below zero
    negative = np.cumsum(np.nan_to_num(increments), axis=1)
    negative[np.isnan(tri)] = np.nan
    found = odp_bootstrap(negative)
    assert isinstance(found, Skipped) and "development column 3" in found.reason


def test_a_triangle_with_no_positive_column_and_a_cut_that_leaves_too_little_stop() -> None:
    zero = np.full((6, 6), np.nan)
    for i in range(6):
        zero[i, : 6 - i] = 0.0
    found = odp_bootstrap(zero)
    assert isinstance(found, Skipped) and "column 0 sums to zero or less" in found.reason
    # only column 0 is positive: one column is left and there is nothing to fit
    one = np.full((6, 6), np.nan)
    for i in range(6):
        one[i, : 6 - i] = 100.0 + i
    found = odp_bootstrap(one)
    assert isinstance(found, Skipped)
    assert found.reason == "too few cells to estimate the scale parameter"


def test_trailing_cut_reads_the_column_sums() -> None:
    incremental = np.array(
        [[5.0, 3.0, 0.0, -1.0], [4.0, 2.0, 0.0, np.nan], [6.0, 1.0, np.nan, np.nan]]
    )
    assert trailing_cut(incremental) == (2, "")
    inside = np.array([[5.0, 0.0, 3.0], [4.0, 0.0, np.nan]])
    kept, reason = trailing_cut(inside)
    assert kept == 0 and "column 1" in reason


# Calibration on a short-tail model: GenIns row parameters and scale, the development pattern of
# its first six columns renormalised, the later columns exactly zero in the model.
CALIBRATION_RUNS = int(os.environ.get("ACTUARYCANARY_CUT_RUNS", 1_000))
CALIBRATION_SIMS = int(os.environ.get("ACTUARYCANARY_CUT_SIMS", 2_000))
CALIBRATION_SEED = 20261109
COVERAGE_RANGE = (0.90, 0.99)
KEPT_COLUMNS = 6


def _short_tail_model() -> tuple[np.ndarray, float]:
    tri, _, _ = triangle("MT11-odp-bootstrap-genins")
    chain = fitted(tri)
    pattern = np.diff(np.concatenate([[0.0], 1 / chain.cdf]))
    pattern[KEPT_COLUMNS:] = 0.0
    pattern = pattern / pattern.sum()
    phi = _run(tri, n_simulations=10).scale_parameter
    return np.outer(chain.ultimate, pattern), phi


@pytest.mark.slow
@MONTE_CARLO
def test_calibration_on_triangles_drawn_from_a_short_tail_model() -> None:
    means, phi = _short_tail_model()
    n = len(means)
    upper = np.add.outer(np.arange(n), np.arange(n)) <= n - 1
    positive = means > 0
    rng = np.random.default_rng(CALIBRATION_SEED)
    hits = []
    started = time.perf_counter()
    for k in range(CALIBRATION_RUNS):
        cells = np.where(positive, rng.gamma(np.where(positive, means / phi, 1.0), phi), 0.0)
        observed = np.where(upper, np.cumsum(np.where(upper, cells, 0.0), axis=1), np.nan)
        result = odp_bootstrap(
            observed, generator(CALIBRATION_SEED, str(k)), n_simulations=CALIBRATION_SIMS
        )
        assert isinstance(result, OdpBootstrap)
        assert result.cut_columns == tuple(range(KEPT_COLUMNS, n))
        hits.append(float(cells[~upper].sum()) <= np.quantile(result.total, 0.95))
    coverage = float(np.mean(hits))
    print(
        f"MT11 on a short-tail model: coverage of the 95th percentile {coverage:.3f} over "
        f"{CALIBRATION_RUNS} triangles with {CALIBRATION_SIMS} simulations, "
        f"{time.perf_counter() - started:.0f} s"
    )
    low, high = COVERAGE_RANGE
    assert low <= coverage <= high, coverage
