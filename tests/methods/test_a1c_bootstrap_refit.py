"""A1c, R04 (records 0782 and 0783): a development column that rests on fewer link ratios of the
triangle than the rule's limit takes the factor 1.000 in the refit of every pseudo-triangle."""

import numpy as np
import pytest

from actuarycanary.methods import odp_bootstrap as module
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, _refit_and_project, odp_bootstrap
from tests.benchmarks.load import load_benchmark
from tests.methods.test_a1b_bootstrap_diagnostics import _refit_and_project_before


def _raa() -> np.ndarray:
    rows = load_benchmark("raa")["triangle"]["values"]
    return np.array([[np.nan if v is None else v for v in r] for r in rows])


def test_a_thin_last_column_gets_the_factor_one_and_the_projection_follows() -> None:
    """3 x 3 pseudo-triangle; the last factor rests on one origin. By hand: factor 0-1 is
    (30 + 24) / (10 + 8) = 3; factor 1-2 would be 33 / 30 = 1.1 and is 1.000 under the rule."""
    observed = np.array([[True, True, True], [True, True, False], [True, False, False]])
    latest_index = np.array([2, 1, 0])
    pseudo = np.array([[[10.0, 20.0, 3.0], [8.0, 16.0, 0.0], [5.0, 0.0, 0.0]]])
    thin = np.array([False, True])
    future, tail, defects = _refit_and_project(
        pseudo, observed, latest_index, 1.0, np.array([3.0, 1.1]), thin
    )
    # origin 1: latest 24, factor 1-2 is 1.000, nothing more to pay
    assert future[0, 1, 2] == pytest.approx(0.0)
    # origin 2: latest 5, 5 x 3 = 15 -> increment 10, then factor 1.000 -> 0
    assert future[0, 2, 1] == pytest.approx(10.0)
    assert future[0, 2, 2] == pytest.approx(0.0)
    np.testing.assert_array_equal(tail, np.zeros((1, 3)))
    # without the rule the last factor is 1.1: origin 1 pays 2.4 more
    plain, _, _ = _refit_and_project(pseudo, observed, latest_index, 1.0, np.array([3.0, 1.1]))
    assert plain[0, 1, 2] == pytest.approx(2.4)
    assert not defects["extreme_factor"].any()


def test_a_ruled_column_is_not_counted_as_a_defect() -> None:
    observed = np.array([[True, True, True], [True, True, False], [True, False, False]])
    latest_index = np.array([2, 1, 0])
    pseudo = np.array([[[10.0, 20.0, 90.0], [8.0, 16.0, 0.0], [5.0, 0.0, 0.0]]])  # factor 4
    fitted = np.array([3.0, 1.1])
    _, _, plain = _refit_and_project(pseudo, observed, latest_index, 1.0, fitted)
    _, _, ruled = _refit_and_project(
        pseudo, observed, latest_index, 1.0, fitted, np.array([False, True])
    )
    assert plain["extreme_factor"].all() and not ruled["extreme_factor"].any()


def test_the_setting_one_gives_the_reserves_of_the_a1b_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    triangle = _raa()
    now = odp_bootstrap(triangle, n_simulations=2000, seed=11, min_link_ratios=1)

    def before(pseudo, observed, latest_index, tail_factor, fitted_factors=None, thin=None):
        future, tail = _refit_and_project_before(pseudo, observed, latest_index, tail_factor)
        none = np.zeros(len(pseudo), dtype=bool)
        kinds = ("zero_denominator", "negative_cumulative", "extreme_factor")
        return future, tail, dict.fromkeys(kinds, none)

    monkeypatch.setattr(module, "_refit_and_project", before)
    then = odp_bootstrap(triangle, n_simulations=2000, seed=11)
    assert isinstance(now, OdpBootstrap) and isinstance(then, OdpBootstrap)
    np.testing.assert_array_equal(now.reserves, then.reserves)
    np.testing.assert_array_equal(now.cash_flows, then.cash_flows)
    assert now.ruled_columns == ()


def _fixed_count_process(rng, means, phi, process):
    """A process step that takes the same number of draws whatever the means: the gamma sampler
    rejects a number of candidates that depends on its shape, so with it the stream after a run
    moves whenever a mean moves, without any reordering (record 0783)."""
    return means + rng.standard_normal(means.shape)


def test_the_rule_makes_no_draw_and_keeps_the_order_of_the_draws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_process", _fixed_count_process)
    after = []
    for limit in (1, 2):
        rng = np.random.default_rng(5)
        odp_bootstrap(_raa(), rng, n_simulations=1500, min_link_ratios=limit)
        after.append(rng.random(4))
    np.testing.assert_array_equal(after[0], after[1])  # the next draws are the same


def test_the_rule_moves_only_the_thin_column() -> None:
    triangle = _raa()
    results = [
        odp_bootstrap(triangle, np.random.default_rng(5), n_simulations=1500, min_link_ratios=k)
        for k in (1, 2)
    ]
    plain, ruled = results
    assert isinstance(plain, OdpBootstrap) and isinstance(ruled, OdpBootstrap)
    assert ruled.ruled_columns == (8,) and ruled.min_link_ratios == 2
    # the fitted model, the residuals and the scale are those of the plain run (decision 5)
    np.testing.assert_array_equal(ruled.chain.factors, plain.chain.factors)
    np.testing.assert_array_equal(ruled.pool, plain.pool)
    assert ruled.scale_parameter == plain.scale_parameter
    # origin 1 (latest at column 8) has only the last column ahead: under the rule its mean is
    # 0, so every simulated value is a process draw of mean 0, that is 0
    np.testing.assert_array_equal(ruled.reserves[:, 1], np.zeros(1500))
    assert np.abs(plain.reserves[:, 1]).sum() > 0


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="min_link_ratios"):
        odp_bootstrap(_raa(), n_simulations=10, min_link_ratios=0)


# --- remedy (b): the floor of the pseudo increments (record 0784) ---------------------------


def test_the_floor_by_hand() -> None:
    """Cells -5, 3, -1, -7 with observed increments 2, 4, -3, -3: the floor is 0, 0, -3, -3,
    so the guard gives 0, 3, -1, -3."""
    pseudo = np.array([[-5.0, 3.0, -1.0, -7.0]])
    floor = np.minimum(np.array([2.0, 4.0, -3.0, -3.0]), 0.0)
    np.testing.assert_array_equal(module._floor(pseudo, floor), [[0.0, 3.0, -1.0, -3.0]])


def test_the_floor_keeps_every_pseudo_cumulative_at_or_above_zero() -> None:
    result = odp_bootstrap(_raa(), n_simulations=2000, seed=3, floor_pseudo_increments=True)
    plain = odp_bootstrap(_raa(), n_simulations=2000, seed=3)
    assert isinstance(result, OdpBootstrap) and isinstance(plain, OdpBootstrap)
    assert plain.pseudo_negative_cumulative > 0  # RAA without the guard has some
    assert result.pseudo_negative_cumulative == 0 and result.pseudo_zero_denominator == 0
    assert result.floor_pseudo_increments


def _smooth() -> np.ndarray:
    """A chain-ladder triangle with small noise on large cells: no pseudo cell is negative."""
    pattern = np.array([0.4, 0.3, 0.15, 0.1, 0.05])
    noise = np.random.default_rng(2).normal(1.0, 0.01, size=(6, 5))
    incremental = 1e8 * np.outer(np.linspace(1.0, 1.5, 6), pattern) * noise
    cumulative = np.cumsum(incremental, axis=1)
    cumulative[np.add.outer(np.arange(6), np.arange(5)) > 5] = np.nan
    return cumulative


def test_where_the_floor_does_not_act_the_reserves_are_bit_identical() -> None:
    off = odp_bootstrap(_smooth(), n_simulations=2000, seed=4, min_link_ratios=2)
    on = odp_bootstrap(
        _smooth(), n_simulations=2000, seed=4, min_link_ratios=2, floor_pseudo_increments=True
    )
    assert isinstance(off, OdpBootstrap) and isinstance(on, OdpBootstrap)
    assert off.pseudo_negative_cumulative == 0
    np.testing.assert_array_equal(on.reserves, off.reserves)
    np.testing.assert_array_equal(on.cash_flows, off.cash_flows)


def test_the_floor_makes_no_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_process", _fixed_count_process)
    after = []
    for floor in (False, True):
        rng = np.random.default_rng(8)
        odp_bootstrap(_raa(), rng, n_simulations=1500, floor_pseudo_increments=floor)
        after.append(rng.random(4))
    np.testing.assert_array_equal(after[0], after[1])
