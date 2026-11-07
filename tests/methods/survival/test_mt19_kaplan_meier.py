"""MT19 Kaplan-Meier: the ten-time hand fixture, Greenwood variance, log-log intervals,
percentiles of the time to event and the log-rank test.

Spec IDs proved: MT19.
"""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy import stats

from actuarycanary.methods.survival.kaplan_meier import (
    kaplan_meier,
    log_rank,
    percentile_time,
    survival_at,
)
from tests.methods.survival.helpers import hand_times, reference

_, VALUES = reference("MT19-kaplan-meier-ten-times")
EVENT_TIMES = (2, 3, 5, 7, 9)


def _frozen(quantity: str, key) -> float:
    return VALUES[(quantity, str(key))]["value"]


@pytest.fixture(scope="module")
def curve():
    time, event = hand_times()
    return kaplan_meier(time, event)


def test_the_event_times_at_risk_and_events_are_the_hand_counts(curve) -> None:
    assert list(curve.time) == list(EVENT_TIMES)
    for index, t in enumerate(EVENT_TIMES):
        assert curve.at_risk[index] == _frozen("at_risk", t)
        assert curve.events[index] == _frozen("events", t)


@pytest.mark.parametrize(
    "quantity,attribute",
    [
        ("survival", "survival"),
        ("greenwood_sum", "greenwood_sum"),
        ("greenwood_standard_error", "standard_error"),
    ],
)
def test_survival_and_greenwood_agree_with_the_hand_values_to_1e_12(
    curve, quantity: str, attribute: str
) -> None:
    for index, t in enumerate(EVENT_TIMES):
        assert getattr(curve, attribute)[index] == pytest.approx(_frozen(quantity, t), rel=1e-12)


def test_greenwood_variance_is_survival_squared_times_the_sum(curve) -> None:
    for index, t in enumerate(EVENT_TIMES):
        variance = curve.survival[index] ** 2 * curve.greenwood_sum[index]
        assert variance == pytest.approx(_frozen("greenwood_variance", t), rel=1e-12)


def test_the_log_log_interval_agrees_with_the_hand_values_to_1e_9(curve) -> None:
    for index, t in enumerate(EVENT_TIMES):
        assert curve.lower[index] == pytest.approx(_frozen("log_log_lower_95", t), rel=1e-9)
        assert curve.upper[index] == pytest.approx(_frozen("log_log_upper_95", t), rel=1e-9)


def test_the_median_is_the_first_time_at_or_below_one_half(curve) -> None:
    median, lower, upper = percentile_time(curve, 0.5)
    assert median == _frozen("median", "time") == 7.0
    assert survival_at(curve, 6.9) == pytest.approx(0.5833333333333334, rel=1e-12)
    assert survival_at(curve, 1.0) == 1.0
    # the lower limit of the curve is 0.473 at time 2, already below one half; the upper limit
    # (0.985, 0.892, 0.821, 0.726, 0.587) never gets there: beyond the observed range
    assert lower == 2.0 and math.isnan(upper)


def test_quartiles_of_the_fixture(curve) -> None:
    q1 = percentile_time(curve, 0.25)[0]  # S <= 0.75: first at time 3 (0.7)
    q3 = percentile_time(curve, 0.75)[0]  # S <= 0.25: first at time 9 (0.21875)
    assert (q1, q3) == (3.0, 9.0)


def test_a_curve_that_never_reaches_a_level_is_beyond_the_observed_range() -> None:
    event = np.zeros(40, dtype=bool)
    event[0] = True
    curve = kaplan_meier(np.arange(1.0, 41.0), event)
    assert all(math.isnan(v) for v in percentile_time(curve, 0.5))
    # with four claims the lower limit of the curve (0.13) does get below one half at time 1
    small = kaplan_meier(np.array([1.0, 2.0, 3.0, 4.0]), np.array([True, False, False, False]))
    median, lower, upper = percentile_time(small, 0.5)
    assert math.isnan(median) and lower == 1.0 and math.isnan(upper)


def test_a_censoring_at_an_event_time_stays_in_the_risk_set_of_that_time() -> None:
    curve = kaplan_meier(np.array([5.0, 5.0, 7.0]), np.array([True, False, True]))
    assert list(curve.at_risk) == [3, 1] and list(curve.events) == [1, 1]
    assert curve.survival[0] == pytest.approx(2 / 3, rel=1e-15)
    assert curve.survival[1] == 0.0
    assert math.isnan(curve.standard_error[1]) and math.isnan(curve.lower[1])  # n = d


def test_censored_counts_between_event_times() -> None:
    event = np.array([1, 0, 0, 1, 0, 1], dtype=bool)
    curve = kaplan_meier(np.array([1.0, 2.0, 2.5, 3.0, 4.0, 9.0]), event)
    assert list(curve.time) == [1.0, 3.0, 9.0]
    assert list(curve.censored) == [2, 1, 0]  # after each event time and before the next
    assert curve.n == 6 and curve.n_events == 3 and curve.share_censored == 0.5


def test_a_wider_confidence_gives_a_wider_interval() -> None:
    time, event = hand_times()
    narrow, wide = kaplan_meier(time, event, 0.8), kaplan_meier(time, event, 0.99)
    assert np.all(wide.lower <= narrow.lower) and np.all(wide.upper >= narrow.upper)


@pytest.mark.parametrize("confidence", [0.0, 1.0, 1.5])
def test_the_confidence_must_lie_between_zero_and_one(confidence: float) -> None:
    with pytest.raises(ValueError):
        kaplan_meier(np.array([1.0]), np.array([True]), confidence)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 15), st.booleans()), min_size=3, max_size=40))
def test_the_curve_equals_a_loop_over_the_event_times(rows) -> None:
    time = np.array([t for t, _ in rows], dtype=float)
    event = np.array([e for _, e in rows], dtype=bool)
    curve = kaplan_meier(time, event)
    survival, green = 1.0, 0.0
    for index, t in enumerate(sorted({t for t, e in rows if e})):
        n = sum(1 for tt, _ in rows if tt >= t)
        d = sum(1 for tt, e in rows if tt == t and e)
        survival *= 1 - d / n
        assert curve.at_risk[index] == n and curve.events[index] == d
        assert curve.survival[index] == pytest.approx(survival, abs=1e-14)
        if n > d:
            green += d / (n * (n - d))
            assert curve.greenwood_sum[index] == pytest.approx(green, rel=1e-12)
    assert np.all(np.diff(curve.survival) <= 1e-15)
    inside = np.isfinite(curve.lower)
    assert np.all(curve.lower[inside] <= curve.survival[inside] + 1e-12)
    assert np.all(curve.upper[inside] >= curve.survival[inside] - 1e-12)


def test_log_rank_of_two_equal_groups_is_zero() -> None:
    time = np.array([1.0, 2, 3, 4, 1, 2, 3, 4])
    event = np.ones(8, bool)
    test = log_rank(time, event, np.array(["a"] * 4 + ["b"] * 4))
    assert test.statistic == pytest.approx(0.0, abs=1e-12) and test.p_value == pytest.approx(1.0)
    assert list(test.groups) == ["a", "b"] and test.df == 1


def test_log_rank_observed_minus_expected_sums_to_zero_and_has_the_sign_of_the_hazard() -> None:
    rng = np.random.default_rng(3)
    group = np.repeat(["fast", "slow", "mid"], 60)
    scale = {"fast": 1.0, "slow": 3.0, "mid": 2.0}
    time = np.array([rng.exponential(scale[g]) for g in group])
    event = rng.random(len(time)) < 0.8
    test = log_rank(time, event, group)
    assert (test.observed - test.expected).sum() == pytest.approx(0.0, abs=1e-8)
    by_group = dict(zip(test.groups, test.observed - test.expected, strict=True))
    assert by_group["fast"] > 0 > by_group["slow"]
    assert test.df == 2 and test.p_value < 0.01
    assert test.p_value == pytest.approx(stats.chi2.sf(test.statistic, 2), rel=1e-12)


def test_log_rank_of_one_group_has_no_test() -> None:
    test = log_rank(np.array([1.0, 2.0]), np.array([True, True]), np.array(["a", "a"]))
    assert test.df == 0 and math.isnan(test.p_value)
