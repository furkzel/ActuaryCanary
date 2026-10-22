"""MT03 Bornhuetter–Ferguson: hand fixture, benchmark, properties and failure modes."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.methods.bornhuetter_ferguson import (
    DATA_DERIVED_PRIOR,
    BornhuetterFerguson,
    bornhuetter_ferguson,
)
from actuarycanary.methods.chain_ladder import Skipped
from tests.benchmarks.load import load_benchmark
from tests.methods.helpers import HAND, HAND_PREMIUM, array, fitted, values

FIXTURE_RTOL = 1e-12
BENCHMARK_RTOL = 1e-9


def _run(chain, premium, prior, **options) -> BornhuetterFerguson:
    result = bornhuetter_ferguson(chain, premium, prior, **options)
    assert isinstance(result, BornhuetterFerguson)
    return result


@pytest.mark.parametrize("measure", ["paid", "incurred"])
def test_hand_fixture(measure: str) -> None:
    expected = HAND["expected"][measure]["bornhuetter_ferguson"]
    chain = fitted(array(HAND[measure]))
    result = _run(chain, HAND_PREMIUM, expected["prior_loss_ratio"])
    np.testing.assert_allclose(
        1 - result.percent_unreported, values(expected["percent_developed"]), rtol=FIXTURE_RTOL
    )
    np.testing.assert_allclose(result.ultimate, values(expected["ultimate"]), rtol=FIXTURE_RTOL)
    np.testing.assert_allclose(
        result.ultimate - result.latest, values(expected["ibnr"]), rtol=FIXTURE_RTOL, atol=1e-12
    )
    assert result.ultimate.sum() == pytest.approx(
        expected["total_ultimate"]["value"], rel=FIXTURE_RTOL
    )
    # on an incurred triangle IBNR equals q times the prior ultimate (MT03 output)
    if measure == "incurred":
        np.testing.assert_allclose(
            result.ultimate - result.latest,
            result.percent_unreported * result.prior_ultimate,
            rtol=FIXTURE_RTOL,
            atol=1e-12,
        )


def test_benchmark_matches_the_reference_implementation() -> None:
    benchmark = load_benchmark("clrd_wkcomp")
    expected = benchmark["expected"]
    premium = [benchmark["premium"][o] for o in expected["origins"]]
    bf = expected["bornhuetter_ferguson"]
    result = _run(fitted(array(benchmark["triangle"])), premium, bf["prior_loss_ratio"])
    np.testing.assert_allclose(result.ultimate, bf["ultimate"], rtol=BENCHMARK_RTOL)


def test_fully_developed_origin_keeps_its_latest_value() -> None:
    chain = fitted(array(HAND["paid"]))
    result = _run(chain, HAND_PREMIUM, 5.0)  # q = 0 for 2021 whatever the prior
    assert result.ultimate[0] == chain.latest[0]


@given(st.floats(min_value=0.5, max_value=2.0))
def test_property_prior_equal_to_chain_ladder_ratio_gives_chain_ladder(scale: float) -> None:
    chain = fitted(array(HAND["paid"]))
    premium = HAND_PREMIUM * scale
    result = _run(chain, premium, chain.ultimate / premium)
    np.testing.assert_allclose(result.ultimate, chain.ultimate, rtol=1e-9)


def test_prior_source_is_kept_per_origin() -> None:
    result = _run(fitted(array(HAND["paid"])), HAND_PREMIUM, 0.6, prior_source=DATA_DERIVED_PRIOR)
    assert set(result.prior_source) == {DATA_DERIVED_PRIOR}


@pytest.mark.parametrize("axis", ["first_valuation", "report"])
def test_origin_axis_without_premium_match_is_not_run(axis: str) -> None:
    result = bornhuetter_ferguson(fitted(array(HAND["paid"])), HAND_PREMIUM, 0.6, origin_axis=axis)
    assert result == Skipped(
        "MT03",
        "Bornhuetter–Ferguson needs accident or underwriting origins matched to earned premium",
    )


def test_missing_or_non_positive_premium_skips_only_that_origin() -> None:
    premium = np.array([400.0, np.nan, 0.0, 520.0])
    result = _run(fitted(array(HAND["paid"])), premium, 0.6)
    assert result.not_run == {1: "earned premium missing", 2: "earned premium 0 is not positive"}
    assert np.isnan(result.ultimate[[1, 2]]).all()
    assert result.ultimate[3] == pytest.approx(
        values(HAND["expected"]["paid"]["bornhuetter_ferguson"]["ultimate"])[3]
    )


def test_no_prior_is_not_run() -> None:
    result = bornhuetter_ferguson(fitted(array(HAND["paid"])), HAND_PREMIUM, np.nan)
    assert result == Skipped("MT03", "no prior loss ratio available")


def test_cdf_below_one_is_computed_and_flagged() -> None:
    cumulative = np.array([[100.0, 90.0, 90.0], [100.0, 90.0, np.nan], [100.0, np.nan, np.nan]])
    result = _run(fitted(cumulative), [200.0, 200.0, 200.0], 0.5)
    assert result.negative_unreported.tolist() == [False, False, True]
    assert result.ultimate[2] == pytest.approx(100 + (1 - 1 / 0.9) * 100)
