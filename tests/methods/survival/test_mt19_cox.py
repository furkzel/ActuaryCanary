"""MT19 Cox proportional hazards: the R survival references (Efron and Breslow), the partial
likelihood against a loop written from the specification, exact derivatives, the baseline, the
direction against the log-rank test, concordance and the Grambsch-Therneau test.

Spec IDs proved: MT19.

The Grambsch-Therneau test, the concordance and the baseline survival have no frozen reference
(decision 0616): the tests below check them against independent loops and properties only.
"""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy import stats

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.survival import cox as cox_module
from actuarycanary.methods.survival.cox import (
    baseline_hazard,
    breslow_baseline,
    concordance,
    cox_fit,
    loglik_at,
    proportional_hazards_test,
)
from actuarycanary.methods.survival.kaplan_meier import kaplan_meier, log_rank
from tests.methods.survival.helpers import cox_data, fitted, reference

COVARIATES = {
    "ovarian": ["age", "resid.ds", "rx", "ecog.ps"],
    "lung": ["age", "sex", "ph.ecog"],
}
TIES = ("efron", "breslow")
CASES = [(name, ties) for name in COVARIATES for ties in TIES]


def _fit(name: str, ties: str):
    folder, values = reference(f"MT19-cox-{name}")
    time, event, x = cox_data(folder, COVARIATES[name])
    return fitted(cox_fit(time, event, x, tuple(COVARIATES[name]), ties=ties)), values


def _frozen(values, quantity: str, key: str) -> float:
    return values[(quantity, key)]["value"]


@pytest.mark.parametrize("name,ties", CASES)
def test_coefficients_and_standard_errors_agree_with_r_survival_to_1e_5(name, ties) -> None:
    fit, values = _fit(name, ties)
    for i, covariate in enumerate(COVARIATES[name]):
        assert fit.coefficient[i] == pytest.approx(
            _frozen(values, f"{ties}_coef", covariate), rel=1e-5
        )
        assert fit.standard_error[i] == pytest.approx(
            _frozen(values, f"{ties}_se", covariate), rel=1e-5
        )
        assert fit.z[i] == pytest.approx(_frozen(values, f"{ties}_z", covariate), rel=1e-5)


@pytest.mark.parametrize("name,ties", CASES)
def test_likelihoods_and_the_overall_tests_agree_with_r_survival(name, ties) -> None:
    fit, values = _fit(name, ties)
    assert fit.loglik == pytest.approx(_frozen(values, f"{ties}_loglik", "fit"), rel=1e-5)
    assert fit.loglik_null == pytest.approx(_frozen(values, f"{ties}_loglik", "null"), rel=1e-5)
    assert fit.likelihood_ratio == pytest.approx(
        _frozen(values, f"{ties}_lr_test", "statistic"), rel=1e-5
    )
    # R prints the Wald statistic to four significant digits: 14.25, 29.93, 29.84
    assert fit.wald == pytest.approx(_frozen(values, f"{ties}_wald_test", "statistic"), abs=0.005)
    assert fit.df == len(COVARIATES[name]) and fit.n_events == _frozen(values, "data", "events")
    assert fit.likelihood_ratio_p == pytest.approx(stats.chi2.sf(fit.likelihood_ratio, fit.df))


def test_efron_and_breslow_differ_only_when_event_times_are_tied() -> None:
    ovarian = {t: _fit("ovarian", t)[0] for t in TIES}
    lung = {t: _fit("lung", t)[0] for t in TIES}
    assert np.allclose(ovarian["efron"].coefficient, ovarian["breslow"].coefficient, rtol=1e-9)
    assert not np.allclose(lung["efron"].coefficient, lung["breslow"].coefficient, rtol=1e-4)
    assert lung["efron"].loglik != pytest.approx(lung["breslow"].loglik, rel=1e-6)


def test_hazard_ratios_and_their_interval_follow_the_coefficients() -> None:
    fit, _ = _fit("lung", "efron")
    assert np.allclose(fit.hazard_ratio, np.exp(fit.coefficient), rtol=1e-14)
    half = stats.norm.ppf(0.975) * fit.standard_error
    assert np.allclose(fit.hazard_ratio_lower, np.exp(fit.coefficient - half), rtol=1e-12)
    assert np.allclose(fit.hazard_ratio_upper, np.exp(fit.coefficient + half), rtol=1e-12)
    assert np.allclose(fit.p_value, 2 * stats.norm.sf(np.abs(fit.z)), rtol=1e-12)


# ------------------------------------------------------------------ the likelihood


def _loop_loglik(time, event, x, beta, ties: str) -> float:
    """The log partial likelihood written from the specification, one event time at a time."""
    eta = x @ beta
    total = 0.0
    for t in sorted({t for t, e in zip(time, event, strict=True) if e}):
        risk = [i for i in range(len(time)) if time[i] >= t]
        died = [i for i in risk if time[i] == t and event[i]]
        d = len(died)
        total += sum(eta[i] for i in died)
        denominator = sum(math.exp(eta[i]) for i in risk)
        tied = sum(math.exp(eta[i]) for i in died)
        for r in range(d):
            share = r / d if ties == "efron" else 0.0
            total -= math.log(denominator - share * tied)
    return total


@pytest.mark.parametrize("ties", TIES)
def test_the_partial_likelihood_equals_the_loop_of_the_specification(ties: str) -> None:
    rng = np.random.default_rng(11)
    n = 60
    time = rng.integers(1, 12, n).astype(float)  # many ties
    event = rng.random(n) < 0.7
    x = rng.normal(size=(n, 3))
    for beta in (np.zeros(3), np.array([0.3, -0.5, 0.8]), np.array([-1.2, 0.1, 0.0])):
        assert loglik_at(time, event, x, beta, ties) == pytest.approx(
            _loop_loglik(time, event, x, beta, ties), rel=1e-12
        )


@pytest.mark.parametrize("ties", TIES)
def test_the_gradient_and_the_information_are_the_derivatives_of_the_likelihood(ties) -> None:
    rng = np.random.default_rng(5)
    n = 50
    time = rng.integers(1, 10, n).astype(float)
    event = rng.random(n) < 0.7
    x = rng.normal(size=(n, 2))
    data, _ = cox_module._prepare(time, event, x, ties)
    beta = np.array([0.4, -0.3])
    _, gradient, information = cox_module._partial(beta, data)
    h = 1e-5

    def f(b):
        return cox_module._loglik_and_gradient(b, data)[0]

    for i in range(2):
        e = np.eye(2)[i] * h
        assert gradient[i] == pytest.approx((f(beta + e) - f(beta - e)) / (2 * h), rel=1e-6)
        g_up = cox_module._loglik_and_gradient(beta + e, data)[1]
        g_down = cox_module._loglik_and_gradient(beta - e, data)[1]
        assert np.allclose(-information[i], (g_up - g_down) / (2 * h), rtol=1e-5, atol=1e-7)
    assert np.allclose(information, information.T, rtol=1e-12)


def test_the_fit_is_a_maximum_and_does_not_depend_on_the_time_scale() -> None:
    folder, _ = reference("MT19-cox-lung")
    time, event, x = cox_data(folder, COVARIATES["lung"])
    fit = fitted(cox_fit(time, event, x, tuple(COVARIATES["lung"])))
    scaled = fitted(cox_fit(time / 30.4375, event, x, tuple(COVARIATES["lung"])))
    assert np.allclose(fit.coefficient, scaled.coefficient, rtol=1e-9)
    for i in range(3):
        e = np.eye(3)[i] * 1e-3
        assert loglik_at(time, event, x, fit.coefficient + e) < fit.loglik
        assert loglik_at(time, event, x, fit.coefficient - e) < fit.loglik


# ------------------------------------------------------------------ failures


def test_no_events_is_skipped_with_the_reason() -> None:
    fit = cox_fit(np.array([1.0, 2.0]), np.array([False, False]), np.array([[0.0], [1.0]]), ("a",))
    assert isinstance(fit, Skipped) and fit.reason == "no events"


def test_collinear_covariates_are_skipped() -> None:
    rng = np.random.default_rng(1)
    a = rng.normal(size=40)
    x = np.column_stack([a, 2 * a])
    fit = cox_fit(rng.exponential(size=40), rng.random(40) < 0.8, x, ("a", "b"))
    assert isinstance(fit, Skipped) and "collinear" in fit.reason


def test_a_covariate_that_separates_the_events_has_no_maximum() -> None:
    time = np.arange(1.0, 41.0)
    event = np.ones(40, dtype=bool)
    x = (time <= 20).astype(float).reshape(-1, 1)  # exactly the first 20 die first
    fit = cox_fit(time, event, x, ("early",))
    assert isinstance(fit, Skipped)
    assert "without bound" in fit.reason or "converge" in fit.reason


def test_an_unknown_tie_rule_is_refused() -> None:
    with pytest.raises(ValueError):
        cox_fit(
            np.array([1.0, 2.0]),
            np.array([True, True]),
            np.array([[0.0], [1.0]]),
            ("a",),
            ties="exact",
        )


# ------------------------------------------------------------------ baseline and Kaplan-Meier


@settings(max_examples=30, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 12), st.booleans()), min_size=4, max_size=40))
def test_with_no_covariate_effect_the_baseline_is_the_nelson_aalen_hazard_in_the_km_order(
    rows,
) -> None:
    time = np.array([t for t, _ in rows], dtype=float)
    event = np.array([e for _, e in rows], dtype=bool)
    if not event.any():
        return
    times, hazard = breslow_baseline(time, event, np.zeros((len(time), 1)), np.zeros(1))
    curve = kaplan_meier(time, event)
    assert np.array_equal(times, curve.time)
    assert np.allclose(hazard, np.cumsum(curve.events / curve.at_risk), rtol=1e-12)
    km_hazard = -np.log(curve.survival[curve.survival > 0])
    # the Kaplan-Meier cumulative hazard -ln S is never below the Nelson-Aalen one, and both
    # rise together: the order of any two times is the same
    assert np.all(km_hazard >= hazard[: len(km_hazard)] - 1e-12)
    assert np.all(np.diff(hazard) > 0) and np.all(np.diff(km_hazard) > 0)


def test_the_baseline_of_a_fit_is_nondecreasing_and_starts_at_the_first_increment() -> None:
    fit, _ = _fit("lung", "efron")
    times, hazard = baseline_hazard(fit)
    assert np.all(np.diff(hazard) > 0) and hazard[0] > 0
    assert np.array_equal(times, np.unique(fit.time[fit.event]))


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.tuples(st.integers(1, 15), st.booleans(), st.booleans()), min_size=8, max_size=40)
)
def test_a_binary_covariate_has_the_direction_of_the_log_rank_test(rows) -> None:
    time = np.array([t for t, _, _ in rows], dtype=float)
    event = np.array([e for _, e, _ in rows], dtype=bool)
    flag = np.array([g for _, _, g in rows], dtype=bool)
    if event.sum() < 2 or flag.all() or not flag.any():
        return
    test = log_rank(time, event, np.where(flag, "b", "a"))
    o_minus_e = float((test.observed - test.expected)[test.groups.index("b")])
    # with Breslow ties the score at beta = 0 is exactly observed minus expected, and the
    # log-likelihood is concave, so the maximum lies on the side of the score
    score = cox_module._partial(
        np.zeros(1),
        cox_module._prepare(time, event, flag.astype(float).reshape(-1, 1), "breslow")[0],
    )[1][0]
    assert score == pytest.approx(o_minus_e, abs=1e-9)
    fit = cox_fit(time, event, flag.astype(float).reshape(-1, 1), ("b",), ties="breslow")
    if isinstance(fit, Skipped) or abs(o_minus_e) < 1e-9:
        return
    assert np.sign(fit.coefficient[0]) == np.sign(o_minus_e)


def test_the_wald_and_log_rank_tests_agree_on_a_two_group_sample() -> None:
    rng = np.random.default_rng(8)
    flag = np.repeat([0.0, 1.0], 150)
    time = rng.exponential(1.0 / np.where(flag == 1.0, 1.6, 1.0))
    event = rng.random(300) < 0.85
    fit = fitted(cox_fit(time, event, flag.reshape(-1, 1), ("b",), ties="breslow"))
    test = log_rank(time, event, np.where(flag == 1.0, "b", "a"))
    assert fit.coefficient[0] > 0
    assert fit.likelihood_ratio == pytest.approx(test.statistic, rel=0.05)  # score ~ LR ~ Wald


# ------------------------------------------------------------------ concordance


def _brute_concordance(time, event, score) -> float:
    concordant = discordant = tied = 0.0
    for i in range(len(time)):
        if not event[i]:
            continue
        for j in range(len(time)):
            if i == j or (time[j] < time[i]) or (time[j] == time[i] and event[j]):
                continue
            if score[i] > score[j]:
                concordant += 1
            elif score[i] < score[j]:
                discordant += 1
            else:
                tied += 1
    total = concordant + discordant + tied
    return (concordant + 0.5 * tied) / total if total else math.nan


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(1, 10), st.booleans(), st.integers(0, 4)), min_size=3, max_size=40
    )
)
def test_concordance_equals_the_pairwise_count(rows) -> None:
    time = np.array([t for t, _, _ in rows], dtype=float)
    event = np.array([e for _, e, _ in rows], dtype=bool)
    score = np.array([s for _, _, s in rows], dtype=float)
    expected = _brute_concordance(time, event, score)
    got = concordance(time, event, score)
    assert (math.isnan(expected) and math.isnan(got)) or got == pytest.approx(expected, abs=1e-12)


def test_concordance_of_a_perfect_ordering_is_one_and_of_the_reverse_is_zero() -> None:
    time = np.arange(1.0, 11.0)
    event = np.ones(10, dtype=bool)
    assert concordance(time, event, -time) == 1.0  # longer time, lower risk
    assert concordance(time, event, time) == 0.0
    assert concordance(time, event, np.zeros(10)) == 0.5


def test_the_concordance_of_the_lung_fit_is_between_one_half_and_one() -> None:
    fit, _ = _fit("lung", "efron")
    assert 0.5 < fit.concordance < 1.0
    folder, _ = reference("MT19-cox-lung")
    time, event, x = cox_data(folder, COVARIATES["lung"])
    assert fit.concordance == pytest.approx(
        _brute_concordance(time, event, np.round(x @ fit.coefficient, 12)), abs=1e-12
    )


# ------------------------------------------------------------------ proportional hazards test


def _loop_ph_test(fit) -> tuple[np.ndarray, float]:
    """The Schoenfeld-residual test written event by event (no ties, so Efron = Breslow)."""
    order = np.argsort(fit.time)
    time, event, x = fit.time[order], fit.event[order], fit.x[order]
    w = np.exp(x @ fit.coefficient)
    residuals, times = [], []
    for i in np.flatnonzero(event):
        risk = time >= time[i]
        mean = (w[risk, None] * x[risk]).sum(axis=0) / w[risk].sum()
        residuals.append(x[i] - mean)
        times.append(time[i])
    r = np.array(residuals)
    d = len(r)
    before = []  # Kaplan-Meier survival just before each event time, by a loop
    for t in times:
        value = 1.0
        for s in sorted({u for u, e in zip(time, event, strict=True) if e and u < t}):
            at_risk = int(np.sum(time >= s))
            value *= 1.0 - np.sum((time == s) & event) / at_risk
        before.append(value)
    g = 1.0 - np.array(before)
    centred = g - g.mean()
    v = fit.covariance
    z = d * (centred @ (r @ v)) ** 2 / (np.diag(v) * np.sum(centred**2))
    return z, float(d * (centred @ r) @ v @ (centred @ r) / np.sum(centred**2))


def test_the_grambsch_therneau_test_equals_the_loop_on_the_ovarian_data() -> None:
    fit, _ = _fit("ovarian", "efron")  # no tied event times
    test = proportional_hazards_test(fit)
    z, global_statistic = _loop_ph_test(fit)
    assert np.allclose(test.statistic, z, rtol=1e-9)
    assert test.global_statistic == pytest.approx(global_statistic, rel=1e-9)
    assert test.global_df == 4 and np.all((test.p_value >= 0) & (test.p_value <= 1))
    assert test.global_p_value == pytest.approx(stats.chi2.sf(test.global_statistic, 4))
    assert test.scaled_residuals.shape == (fit.n_events, 4)


def test_the_test_passes_proportional_hazards_and_rejects_crossing_hazards() -> None:
    rng = np.random.default_rng(21)
    n = 1500
    flag = rng.integers(0, 2, n).astype(float)
    # proportional: exponential with a constant ratio
    prop_time = rng.exponential(1.0 / np.where(flag == 1.0, 2.0, 1.0))
    # crossing: Weibull shape 0.6 in one group and 2.5 in the other (survival curves cross)
    cross_time = np.where(flag == 1.0, rng.weibull(0.6, n), rng.weibull(2.5, n))
    event = np.ones(n, dtype=bool)
    proportional = fitted(cox_fit(prop_time, event, flag.reshape(-1, 1), ("b",)))
    crossing = fitted(cox_fit(cross_time, event, flag.reshape(-1, 1), ("b",)))
    assert proportional_hazards_test(proportional).global_p_value > 0.01
    assert proportional_hazards_test(crossing).global_p_value < 1e-6
