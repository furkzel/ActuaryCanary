"""A1b, R04 (record 0778): the defects of the bootstrap's pseudo-triangles are counted from the
arrays the refit has anyway and move no draw and no figure."""

import numpy as np
import pytest

from actuarycanary.methods import odp_bootstrap as module
from actuarycanary.methods.odp_bootstrap import (
    EXTREME_FACTOR_MULTIPLE,
    PSEUDO_SHARE_WARNING,
    OdpBootstrap,
    _refit_and_project,
    odp_bootstrap,
)
from tests.benchmarks.load import load_benchmark


def _triangle(name: str) -> np.ndarray:
    rows = load_benchmark(name)["triangle"]["values"]
    return np.array([[np.nan if v is None else v for v in r] for r in rows])


def _refit_and_project_before(pseudo, observed, latest_index, tail_factor):
    """The refit as it was before the counting (MT11 1.2.0), kept here as the reference."""
    batch, n_origins, n_dev = pseudo.shape
    cumulative = np.cumsum(np.where(observed, pseudo, 0.0), axis=2)
    both = observed[:, 1:] & observed[:, :-1]
    numerator = (cumulative[:, :, 1:] * both).sum(axis=1)
    denominator = (cumulative[:, :, :-1] * both).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        factors = np.where(denominator != 0, numerator / denominator, 1.0)
    rows = np.arange(n_origins)
    latest = cumulative[:, rows, latest_index]
    projected = np.empty((batch, n_origins, n_dev))
    projected[:, rows, latest_index] = latest
    for j in range(n_dev - 1):
        later = latest_index <= j
        projected[:, later, j + 1] = projected[:, later, j] * factors[:, j, None]
    future = np.full((batch, n_origins, n_dev), np.nan)
    future[:, :, 1:] = projected[:, :, 1:] - projected[:, :, :-1]
    future[:, observed] = np.nan
    tail = projected[:, :, -1] * (tail_factor - 1)
    return future, tail


def _shape() -> tuple[np.ndarray, np.ndarray]:
    n = 5
    observed = np.add.outer(np.arange(n), np.arange(n)) < n
    return observed, n - 1 - np.arange(n)


def test_the_refit_returns_what_it_returned_before_bit_for_bit() -> None:
    observed, latest_index = _shape()
    rng = np.random.default_rng(3)
    pseudo = rng.normal(100.0, 80.0, size=(400, 5, 5))  # many negative cells and bad columns
    new = _refit_and_project(pseudo, observed, latest_index, 1.1, np.full(4, 1.2))
    old = _refit_and_project_before(pseudo, observed, latest_index, 1.1)
    np.testing.assert_array_equal(new[0], old[0])
    np.testing.assert_array_equal(new[1], old[1])


def test_the_whole_bootstrap_is_unchanged_by_the_counting(monkeypatch: pytest.MonkeyPatch) -> None:
    triangle = _triangle("raa")
    counted = odp_bootstrap(triangle, n_simulations=2500, seed=7)

    def before(pseudo, observed, latest_index, tail_factor, fitted_factors=None, thin=None):
        future, tail = _refit_and_project_before(pseudo, observed, latest_index, tail_factor)
        none = np.zeros(len(pseudo), dtype=bool)
        return (
            future,
            tail,
            {"zero_denominator": none, "negative_cumulative": none, "extreme_factor": none},
        )

    monkeypatch.setattr(module, "_refit_and_project", before)
    plain = odp_bootstrap(triangle, n_simulations=2500, seed=7)
    assert isinstance(counted, OdpBootstrap) and isinstance(plain, OdpBootstrap)
    np.testing.assert_array_equal(counted.reserves, plain.reserves)
    np.testing.assert_array_equal(counted.cash_flows, plain.cash_flows)
    assert plain.pseudo_negative_cumulative == 0 and counted.pseudo_negative_cumulative > 0


def test_each_kind_is_counted_on_pseudo_triangles_made_by_hand() -> None:
    observed, latest_index = _shape()
    good = np.where(observed, 100.0, 0.0)  # factors 1.0 against fitted 1.0
    zero = good.copy()
    zero[:, 0] = 0.0  # the denominator of column 0 is zero
    negative = good.copy()
    negative[3, 1] = -1000.0  # a negative increment drives the cumulative value below zero
    wild = good.copy()
    wild[0, 4] = 5000.0  # the last factor is far above twice the fitted one
    pseudo = np.stack([good, zero, negative, wild])
    _, _, found = _refit_and_project(pseudo, observed, latest_index, 1.0, np.ones(4))
    assert found["zero_denominator"].tolist() == [False, True, False, False]
    assert found["negative_cumulative"].tolist() == [False, False, True, False]
    # the negative cell also makes the factor of column 0 negative; the last factor of the
    # fourth is far above twice the fitted one
    assert found["extreme_factor"].tolist() == [False, False, True, True]
    assert EXTREME_FACTOR_MULTIPLE == 2.0


def test_shares_and_diagnostics_follow_the_limit() -> None:
    raa = odp_bootstrap(_triangle("raa"), n_simulations=2000, seed=7)
    genins = odp_bootstrap(_triangle("genins"), n_simulations=2000, seed=7)
    assert isinstance(raa, OdpBootstrap) and isinstance(genins, OdpBootstrap)
    assert raa.pseudo_shares["negative_cumulative"] > PSEUDO_SHARE_WARNING
    assert "PSEUDO_NEGATIVE_CUMULATIVE" in {d.code for d in raa.diagnostics}
    assert raa.pseudo_shares["negative_cumulative"] == raa.pseudo_negative_cumulative / 2000
    assert genins.pseudo_shares == {
        "zero_denominator": 0.0,
        "negative_cumulative": 0.0,
        "extreme_factor": 0.0,
    }
    assert not {d.code for d in genins.diagnostics if d.code.startswith("PSEUDO_")}
    warned = next(d for d in raa.diagnostics if d.code == "PSEUDO_NEGATIVE_CUMULATIVE")
    assert warned.severity == "WARNING" and warned.value == raa.pseudo_shares["negative_cumulative"]
