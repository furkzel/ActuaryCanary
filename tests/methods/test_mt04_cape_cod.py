"""MT04 Cape Cod: hand fixture, benchmark and failure modes."""

import numpy as np
import pytest

from actuarycanary.methods.cape_cod import CapeCod, cape_cod
from actuarycanary.methods.chain_ladder import Skipped
from tests.benchmarks.load import load_benchmark
from tests.methods.helpers import HAND, HAND_PREMIUM, array, fitted, values

FIXTURE_RTOL = 1e-12
BENCHMARK_RTOL = 1e-9


def _run(chain, premium, **options) -> CapeCod:
    result = cape_cod(chain, premium, **options)
    assert isinstance(result, CapeCod)
    return result


@pytest.mark.parametrize("measure", ["paid", "incurred"])
def test_hand_fixture(measure: str) -> None:
    expected = HAND["expected"][measure]["cape_cod"]
    result = _run(fitted(array(HAND[measure])), HAND_PREMIUM)
    np.testing.assert_allclose(
        result.used_up_premium, values(expected["used_up_premium"]), rtol=FIXTURE_RTOL
    )
    assert result.expected_loss_ratio == pytest.approx(
        expected["loss_ratio"]["value"], rel=FIXTURE_RTOL
    )
    np.testing.assert_allclose(result.ultimate, values(expected["ultimate"]), rtol=FIXTURE_RTOL)
    np.testing.assert_allclose(
        result.ultimate - result.latest, values(expected["ibnr"]), rtol=FIXTURE_RTOL, atol=1e-12
    )


def test_benchmark_matches_the_reference_implementation() -> None:
    benchmark = load_benchmark("clrd_wkcomp")
    expected = benchmark["expected"]
    premium = [benchmark["premium"][o] for o in expected["origins"]]
    result = _run(fitted(array(benchmark["triangle"])), premium)
    assert result.expected_loss_ratio == pytest.approx(
        expected["cape_cod"]["loss_ratio"], rel=BENCHMARK_RTOL
    )
    np.testing.assert_allclose(
        result.ultimate, expected["cape_cod"]["ultimate"], rtol=BENCHMARK_RTOL
    )


def test_chain_ladder_loss_ratio_per_origin_is_shown_next_to_the_ratio() -> None:
    chain = fitted(array(HAND["paid"]))
    result = _run(chain, HAND_PREMIUM)
    np.testing.assert_allclose(result.chain_ladder_loss_ratio, chain.ultimate / HAND_PREMIUM)


def test_origins_without_positive_premium_are_left_out_of_the_ratio() -> None:
    chain = fitted(array(HAND["paid"]))
    premium = np.array([400.0, 440.0, -1.0, 520.0])
    result = _run(chain, premium)
    used = [0, 1, 3]
    expected = chain.latest[used].sum() / (premium[used] / chain.cdf_at_latest[used]).sum()
    assert result.expected_loss_ratio == pytest.approx(expected, rel=FIXTURE_RTOL)
    assert result.not_run == {2: "earned premium -1 is not positive"}
    assert np.isnan(result.ultimate[2])


def test_no_positive_premium_is_not_run() -> None:
    result = cape_cod(fitted(array(HAND["paid"])), [0.0, np.nan, 0.0, -5.0])
    assert result == Skipped("MT04", "no origin with positive earned premium")


def test_first_valuation_origins_are_not_run() -> None:
    result = cape_cod(fitted(array(HAND["paid"])), HAND_PREMIUM, origin_axis="first_valuation")
    assert isinstance(result, Skipped)
    assert result.reason.startswith("Cape Cod needs accident or underwriting origins")
