"""MT13 Benktander blends: hand fixture, benchmarks, properties and failure modes."""

import numpy as np
import pytest

from actuarycanary.methods.benktander import Benktander, Prior, benktander, prior_ultimate
from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson, bornhuetter_ferguson
from actuarycanary.methods.cape_cod import CapeCod, cape_cod
from actuarycanary.methods.chain_ladder import Skipped
from tests.methods.helpers import fitted
from tests.methods.tier_b import reference, series, table, triangle

HAND = "MT13-benktander-4x4"


def _run(chain, prior, **options) -> Benktander:
    result = benktander(chain, prior, **options)
    assert isinstance(result, Benktander)
    return result


@pytest.mark.parametrize("basis", ["paid", "incurred"])
def test_hand_fixture_k1_and_k2(basis: str) -> None:
    tri, _, _ = triangle(HAND, f"{basis}_triangle.csv")
    premium = np.array([float(r["earned_premium"]) for r in table(HAND, "premium.csv")])
    chain = fitted(tri)
    bf = bornhuetter_ferguson(chain, premium, 0.6)
    assert isinstance(bf, BornhuetterFerguson)
    k1, k2 = _run(chain, bf, iterations=1), _run(chain, bf, iterations=2)
    rtol = 1e-12
    np.testing.assert_allclose(
        k1.reported_share, series(HAND, f"{basis}_reported_share_p"), rtol=rtol
    )
    np.testing.assert_allclose(
        k1.bornhuetter_ferguson_ultimate,
        series(HAND, f"{basis}_bornhuetter_ferguson_ultimate"),
        rtol=rtol,
    )
    np.testing.assert_allclose(
        k1.ultimate, series(HAND, f"{basis}_benktander_k1_ultimate"), rtol=rtol
    )
    np.testing.assert_allclose(
        k2.ultimate, series(HAND, f"{basis}_benktander_k2_ultimate"), rtol=rtol
    )
    np.testing.assert_allclose(
        k1.weight, series(HAND, f"{basis}_benktander_weight_on_chain_ladder_k1"), rtol=rtol
    )
    np.testing.assert_allclose(
        k1.chain_ladder_ultimate, series(HAND, f"{basis}_chain_ladder_ultimate"), rtol=rtol
    )


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_benchmark_against_the_package(name: str) -> None:
    ref = f"MT13-benktander-{name}"
    tri, _, _ = triangle(ref)
    prior = reference(ref)["manifest"]["prior"]
    u0 = np.full(len(tri), prior["earned_premium_each_origin"] * prior["prior_loss_ratio"])
    chain = fitted(tri)
    for k in (1, 2):
        result = _run(chain, u0, iterations=k)
        np.testing.assert_allclose(
            result.ultimate, series(ref, f"benktander_k{k}_ultimate"), rtol=1e-9
        )
    np.testing.assert_allclose(
        _run(chain, u0, iterations=0).ultimate,
        series(ref, "bornhuetter_ferguson_ultimate"),
        rtol=1e-9,
    )
    np.testing.assert_allclose(result.reported_share, series(ref, "reported_share_p"), rtol=1e-9)


def test_k0_is_bornhuetter_ferguson_and_large_k_the_chain_ladder() -> None:
    tri, _, _ = triangle("MT13-benktander-genins")
    chain = fitted(tri)
    u0 = np.full(len(tri), 4.5e6)
    np.testing.assert_allclose(
        _run(chain, u0, iterations=0).ultimate, chain.latest + (1 - 1 / chain.cdf_at_latest) * u0,
        rtol=1e-9,
    )  # fmt: skip
    far = _run(chain, u0, iterations=200)
    developed = far.reported_share > 0.2
    np.testing.assert_allclose(far.ultimate[developed], chain.ultimate[developed], rtol=1e-9)


@pytest.mark.parametrize("k", [0, 1, 2, 5])
def test_iterated_and_closed_form_agree(k: int) -> None:
    tri, _, _ = triangle("MT13-benktander-raa")
    chain = fitted(tri)
    result = _run(chain, np.linspace(15000, 25000, len(tri)), iterations=k)
    reserve_cl = chain.ultimate - chain.latest
    reserve_bf = result.bornhuetter_ferguson_ultimate - chain.latest
    closed = result.weight * reserve_cl + (1 - result.weight) * reserve_bf
    np.testing.assert_allclose(result.reserve, closed, rtol=1e-9, atol=1e-6)


def test_prior_of_cape_cod() -> None:
    tri, _, _ = triangle(HAND, "incurred_triangle.csv")
    premium = np.array([400.0, 440.0, 480.0, 520.0])
    chain = fitted(tri)
    cc = cape_cod(chain, premium)
    assert isinstance(cc, CapeCod)
    result = _run(chain, cc, prior_source=Prior.CAPE_COD)
    np.testing.assert_allclose(result.prior_ultimate, cc.expected_loss_ratio * premium, rtol=1e-12)
    np.testing.assert_allclose(prior_ultimate(cc), result.prior_ultimate)
    assert result.prior is Prior.CAPE_COD


def test_cdf_below_one_caps_the_weight_with_a_warning() -> None:
    shrinking = np.array([[100.0, 90.0, 90.0], [100.0, 90.0, np.nan], [80.0, np.nan, np.nan]])
    chain = fitted(shrinking)
    result = _run(chain, np.full(3, 100.0), iterations=1)
    assert result.reported_share[2] > 1 and result.capped[2]
    assert result.weight[2] == 1.0 and result.ultimate[2] == pytest.approx(chain.ultimate[2])
    assert [(d.code, d.target) for d in result.diagnostics] == [("WEIGHT_CAPPED", "2")]


def test_missing_prior_or_chain_ladder() -> None:
    tri, _, _ = triangle(HAND, "paid_triangle.csv")
    chain = fitted(tri)
    partial = _run(chain, np.array([240.0, np.nan, 288.0, 312.0]))
    assert np.isnan(partial.ultimate[1]) and partial.not_run == {1: "no prior ultimate available"}
    assert isinstance(benktander(chain, np.full(4, np.nan)), Skipped)
    assert benktander(Skipped("MT02", "too few"), np.ones(4)) == Skipped("MT13", "too few")
    assert benktander(chain, Skipped("MT03", "no premium")) == Skipped("MT13", "no premium")
    with pytest.raises(ValueError, match="whole number"):
        benktander(chain, np.ones(4), iterations=-1)
