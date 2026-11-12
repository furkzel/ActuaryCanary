"""A1b, R08: a development factor that rests on fewer link ratios than the rule asks for is
set to 1.000 (MT02), through the selected-factor mechanism; the register shows it (record 0776)."""

from datetime import date

import numpy as np
import pytest

from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.judgement import RULE_WHO, chain_ladder_judged
from actuarycanary.methods.mack import Mack, mack
from tests.benchmarks.load import benchmark_names, load_benchmark
from tests.methods.helpers import HAND, HAND_AGES, HAND_ORIGINS, array, fitted

SCOPE = "NON_LIFE/MOTOR_OD/paid"


def _paid() -> np.ndarray:
    return array(HAND["paid"])


def test_the_last_column_rests_on_one_ratio_and_the_one_before_on_two() -> None:
    result = fitted(_paid())
    assert result.n_ratios.tolist() == [3, 2, 1]
    assert not result.replaced.any()  # the default applies no rule


def test_the_rule_sets_the_single_ratio_column_to_one_and_keeps_the_average() -> None:
    plain = fitted(_paid())
    ruled = fitted(_paid(), min_link_ratios=2)
    assert ruled.factors.tolist() == pytest.approx([1.9, 1.2, 1.0])
    assert ruled.averages.tolist() == pytest.approx(plain.averages.tolist())
    assert ruled.averages[2] == pytest.approx(1.1)
    assert ruled.replaced.tolist() == [False, False, True]
    assert ruled.overridden.tolist() == [False, False, True]
    assert any("column 2 rests on 1 link ratio" in w for w in ruled.warnings)
    # the cumulative factors and the ultimates follow
    assert ruled.cdf[2] == pytest.approx(1.0) and ruled.cdf[1] == pytest.approx(1.2)
    np.testing.assert_allclose(ruled.ultimate[-1], ruled.latest[-1] * 1.9 * 1.2)
    np.testing.assert_allclose(ruled.ultimate[0], plain.ultimate[0])  # fully developed origin


def test_a_higher_rule_replaces_the_columns_below_it() -> None:
    result = fitted(_paid(), min_link_ratios=3)
    assert result.replaced.tolist() == [False, True, True]
    assert result.factors.tolist() == pytest.approx([1.9, 1.0, 1.0])


def test_the_setting_one_leaves_everything_as_before() -> None:
    plain = fitted(_paid())
    same = fitted(_paid(), min_link_ratios=1)
    np.testing.assert_array_equal(same.factors, plain.factors)
    np.testing.assert_array_equal(same.ultimate, plain.ultimate)
    assert same.warnings == plain.warnings


def test_a_column_without_any_ratio_keeps_factor_one_and_its_own_warning() -> None:
    triangle = np.array([[10.0, np.nan], [20.0, np.nan], [30.0, np.nan]])
    result = fitted(triangle, min_link_ratios=2)
    assert result.n_ratios.tolist() == [0] and not result.replaced.any()
    assert result.warnings == ("development column 0 has no usable link ratio; factor set to 1",)


def test_a_selected_factor_wins_over_the_rule() -> None:
    result = fitted(_paid(), min_link_ratios=2, selected={2: 1.05})
    assert result.factors[2] == 1.05
    assert result.overridden[2] and not result.replaced[2]


def test_exclusions_lower_the_count() -> None:
    # leaving one ratio out of column 1 (two ratios) leaves one: replaced under the rule 2
    result = fitted(_paid(), min_link_ratios=2, exclusions=[(0, 1)])
    assert result.n_ratios.tolist() == [3, 1, 1]
    assert result.replaced.tolist() == [False, True, True]


@pytest.mark.parametrize("name", benchmark_names())
def test_benchmarks_are_unchanged_at_function_level_by_default(name: str) -> None:
    benchmark = load_benchmark(name)
    result = fitted(array(benchmark["triangle"]))
    np.testing.assert_allclose(result.factors, benchmark["expected"]["ldf"], rtol=1e-9)
    assert not result.replaced.any()


def test_mack_uses_the_factors_of_the_rule() -> None:
    triangle = array(
        load_benchmark("raa")["triangle"]
    )  # ten origins: the last column has one ratio
    plain = mack(triangle)
    ruled = mack(triangle, min_link_ratios=2)
    assert isinstance(plain, Mack) and isinstance(ruled, Mack)
    assert ruled.chain.factors[-1] == 1.0 and ruled.chain.factors[-2] == plain.chain.factors[-2]
    ordinary = fitted(triangle, min_link_ratios=2)
    np.testing.assert_allclose(ruled.reserve, ordinary.reserve)
    assert ruled.total_reserve != pytest.approx(plain.total_reserve)
    assert np.isfinite(ruled.total_standard_error)


def _user(name: str, value: float, target: str) -> Assumption:
    return Assumption(
        method="MT02", name=name, scope=SCOPE, target=target, value=value,
        who="actuary A", when=date(2026, 10, 22), why="reviewed with claims",
    )  # fmt: skip


def _judged(*entries: Assumption, **options):
    result, used = chain_ladder_judged(
        _paid(), origins=HAND_ORIGINS, ages=HAND_AGES, scope=SCOPE,
        register=AssumptionsRegister(entries=entries), **options,
    )  # fmt: skip
    assert isinstance(result, ChainLadder)
    return result, used


def test_the_register_lists_the_replaced_factor_as_selected_by_the_rule() -> None:
    result, used = _judged(min_link_ratios=2)
    entry = next(e for e in used if e.name == "selected_factor" and e.target == "36-48")
    assert (entry.value, entry.default, entry.who) == (1.0, pytest.approx(1.1), RULE_WHO)
    assert "1 link ratio" in entry.why and "fewer than 2" in entry.why
    assert not entry.is_default
    other = next(e for e in used if e.name == "selected_factor" and e.target == "24-36")
    assert other.is_default and other.value == pytest.approx(1.2)
    assert result.replaced[2]


def test_a_user_entry_wins_in_the_register_too() -> None:
    result, used = _judged(_user("selected_factor", 1.08, "36-48"), min_link_ratios=2)
    entry = next(e for e in used if e.name == "selected_factor" and e.target == "36-48")
    assert (entry.value, entry.who) == (1.08, "actuary A")
    assert not result.replaced[2] and result.factors[2] == 1.08


def test_too_few_origins_still_skips() -> None:
    assert isinstance(chain_ladder(_paid()[:2], min_origins=3, min_link_ratios=2), Skipped)
