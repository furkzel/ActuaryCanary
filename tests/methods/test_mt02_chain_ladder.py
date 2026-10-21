"""MT02 chain ladder: hand fixtures, published benchmarks, edge cases and properties."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from tests.benchmarks.load import benchmark_names, load_benchmark, load_hand

FIXTURE_RTOL = 1e-12  # MT02 fixture tolerance
BENCHMARK_RTOL = 1e-9  # MT02 benchmark tolerance

HAND = load_hand()


def _array(triangle: dict) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in triangle["values"]])


def _run(cumulative: np.ndarray, **options) -> ChainLadder:
    result = chain_ladder(cumulative, **options)
    assert isinstance(result, ChainLadder)
    return result


@pytest.mark.parametrize("measure", ["paid", "incurred"])
def test_hand_fixture(measure: str) -> None:
    expected = HAND["expected"][measure]
    result = _run(_array(HAND[measure]))
    np.testing.assert_allclose(
        result.factors, [f["value"] for f in expected["ldf"]], rtol=FIXTURE_RTOL
    )
    np.testing.assert_allclose(result.cdf, [c["value"] for c in expected["cdf"]], rtol=FIXTURE_RTOL)
    chain = expected["chain_ladder"]
    np.testing.assert_allclose(
        result.ultimate, [u["value"] for u in chain["ultimate"]], rtol=FIXTURE_RTOL
    )
    np.testing.assert_allclose(
        result.reserve, [r["value"] for r in chain["ibnr"]], rtol=FIXTURE_RTOL, atol=1e-12
    )
    assert result.ultimate.sum() == pytest.approx(
        chain["total_ultimate"]["value"], rel=FIXTURE_RTOL
    )


def test_hand_fixture_latest_two_diagonals() -> None:
    # 12-24: origins 2022, 2023 only: (210 + 190) / (110 + 100); 24-36: (200 + 256) / (170 + 210)
    result = _run(_array(HAND["paid"]), n_diagonals=2)
    np.testing.assert_allclose(result.factors, [400 / 210, 456 / 380, 220 / 200], rtol=FIXTURE_RTOL)
    np.testing.assert_allclose(result.ultimate[3], 130 * 400 / 210 * 1.2 * 1.1, rtol=FIXTURE_RTOL)


def test_hand_fixture_with_one_exclusion() -> None:
    # link ratio 2022 at 12-24 left out: (170 + 190) / (90 + 100)
    result = _run(_array(HAND["paid"]), exclusions=[(1, 0)])
    np.testing.assert_allclose(result.factors[0], 360 / 190, rtol=FIXTURE_RTOL)
    assert not result.used[1, 0]


def test_simple_average() -> None:
    # 12-24: (170/90 + 210/110 + 190/100) / 3
    result = _run(_array(HAND["paid"]), average=Average.SIMPLE)
    np.testing.assert_allclose(
        result.factors[0], (170 / 90 + 210 / 110 + 190 / 100) / 3, rtol=FIXTURE_RTOL
    )


@pytest.mark.parametrize("name", benchmark_names())
def test_benchmark_factors_and_ultimates(name: str) -> None:
    benchmark = load_benchmark(name)
    expected = benchmark["expected"]
    result = _run(_array(benchmark["triangle"]))
    np.testing.assert_allclose(result.factors, expected["ldf"], rtol=BENCHMARK_RTOL)
    np.testing.assert_allclose(result.cdf, expected["cdf"], rtol=BENCHMARK_RTOL)
    np.testing.assert_allclose(result.ultimate, expected["ultimate"], rtol=BENCHMARK_RTOL)
    np.testing.assert_allclose(result.reserve, expected["ibnr"], rtol=BENCHMARK_RTOL, atol=1e-9)
    assert result.ultimate.sum() == pytest.approx(expected["total"]["ultimate"], rel=BENCHMARK_RTOL)


def test_fewer_origins_than_needed_is_skipped_with_a_reason() -> None:
    result = chain_ladder(np.array([[1.0, 2.0], [1.0, np.nan]]))
    assert isinstance(result, Skipped)
    assert result.reason == "chain ladder needs at least 3 origin periods"


def test_zero_column_gives_factor_one_with_a_warning_and_zero_latest_is_flagged() -> None:
    cumulative = np.array([[0.0, 10.0, 12.0], [0.0, 0.0, np.nan], [0.0, np.nan, np.nan]])
    result = _run(cumulative)
    assert result.factors.tolist() == [1.0, 1.2]
    assert result.warnings == ("development column 0 has no usable link ratio; factor set to 1",)
    assert result.zero_latest.tolist() == [False, True, True]
    assert result.ultimate[2] == 0.0


def test_negative_cumulative_values_are_flagged() -> None:
    cumulative = np.array([[10.0, 12.0, 13.0], [-5.0, 2.0, np.nan], [4.0, np.nan, np.nan]])
    assert _run(cumulative).negative.tolist() == [False, True, False]


def test_exclude_high_low_only_in_columns_with_five_ratios() -> None:
    cumulative = np.array(
        [
            [100.0, 150.0, 160.0],
            [100.0, 200.0, 210.0],
            [100.0, 110.0, 120.0],
            [100.0, 130.0, np.nan],
            [100.0, 140.0, np.nan],
            [100.0, 120.0, np.nan],
            [100.0, np.nan, np.nan],
        ]
    )
    result = _run(cumulative, exclude_high_low=True)
    # column 0 has six ratios: 2.0 and 1.1 dropped; column 1 has three, all kept
    np.testing.assert_allclose(result.factors[0], (150 + 130 + 140 + 120) / 400, rtol=FIXTURE_RTOL)
    np.testing.assert_allclose(result.factors[1], (160 + 210 + 120) / 460, rtol=FIXTURE_RTOL)


def test_tail_factor_multiplies_every_cumulative_factor() -> None:
    result = _run(_array(HAND["paid"]), tail_factor=1.05)
    np.testing.assert_allclose(result.cdf, np.array([2.508, 1.32, 1.1, 1.0]) * 1.05, rtol=1e-12)


@given(st.floats(min_value=1e-3, max_value=1e6))
def test_property_scaling_scales_ultimates(scale: float) -> None:
    base = _run(_array(HAND["paid"]))
    scaled = _run(_array(HAND["paid"]) * scale)
    np.testing.assert_allclose(scaled.ultimate, base.ultimate * scale, rtol=1e-9)


@given(
    st.lists(st.floats(min_value=1.0, max_value=3.0), min_size=2, max_size=6),
    st.lists(st.floats(min_value=1.0, max_value=1e6), min_size=7, max_size=9),
)
def test_property_identical_development_is_reproduced(
    pattern: list[float], firsts: list[float]
) -> None:
    n_dev, n_origins = len(pattern) + 1, len(firsts)
    full = np.array([[first * np.prod(pattern[:j]) for j in range(n_dev)] for first in firsts])
    observed = full.copy()
    for i in range(n_origins):
        observed[i, n_origins - i :] = np.nan  # the usual triangle: i + j <= I - 1
    result = _run(observed)
    np.testing.assert_allclose(result.factors, pattern, rtol=1e-9)
    np.testing.assert_allclose(result.ultimate, full[:, -1], rtol=1e-9)
