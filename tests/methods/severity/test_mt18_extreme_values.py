"""MT18 extreme value analysis: the generalised Pareto fit against the frozen scipy references, the
closed forms of the tail quantile, return level and expected shortfall, ForwardStop, the threshold
candidates, and the threshold rule on both branches (enough excesses, too few).

Spec IDs proved: MT18 (and the threshold comparison of CV08 1.1.0, record 0601).
"""

import math
from typing import Any

import numpy as np
import polars as pl
import pytest
from scipy import optimize, stats

from actuarycanary.methods.severity import evt, gpd
from actuarycanary.methods.severity.evt import extreme_values, forward_stop
from tests.benchmarks.load import load_reference
from tests.methods.severity.helpers import (
    gpd_samples,
    sizes_frame,
    spliced_quantile,
    spliced_sizes,
)

FROZEN = load_reference("MT18-gpd-fits")["values"]
CLOSED_FORMS = load_reference("MT18-gpd-closed-forms")["values"]
FAST: dict[str, Any] = {"gof_bootstrap": 40}


def _frozen(quantity: str, key: str) -> float:
    return FROZEN[(quantity, key)]["value"]


def _closed(quantity: str, key: str) -> float:
    return CLOSED_FORMS[(quantity, key)]["value"]


# ------------------------------------------------------------------ fixtures


@pytest.mark.parametrize("p", [0.99, 0.995])
@pytest.mark.parametrize(("xi", "tag"), [(0.25, "xi_0.25"), (0.0, "xi_0")])
def test_tail_quantile_and_expected_shortfall_are_the_closed_forms(
    p: float, xi: float, tag: str
) -> None:
    u, sigma, n, n_u = 100.0, 50.0, 2000, 100
    x_p = gpd.tail_quantile(p, u, xi, sigma, n, n_u)
    assert x_p == pytest.approx(_closed(f"quantile_{tag}", f"p{p}"), rel=1e-12)
    es = gpd.expected_shortfall(x_p, u, xi, sigma)
    assert es == pytest.approx(_closed(f"expected_shortfall_{tag}", f"p{p}"), rel=1e-12)


@pytest.mark.parametrize(("xi", "tag"), [(0.25, "xi_0.25"), (0.0, "xi_0")])
@pytest.mark.parametrize("years", [10, 50])
def test_return_levels_are_the_closed_forms(xi: float, tag: str, years: int) -> None:
    level = gpd.return_level(years, 100.0, xi, 50.0, 100, 10.0)
    assert level == pytest.approx(_closed(f"return_level_{tag}", f"T{years}"), rel=1e-12)


def test_the_exponential_limit_is_continuous_with_small_xi() -> None:
    near = gpd.tail_quantile(0.99, 100.0, 1e-5, 50.0, 2000, 100)
    exact = gpd.tail_quantile(0.99, 100.0, 0.0, 50.0, 2000, 100)
    assert near == pytest.approx(exact, rel=1e-4)
    assert gpd.return_level(10, 100.0, 1e-5, 50.0, 100, 10.0) == pytest.approx(
        gpd.return_level(10, 100.0, 0.0, 50.0, 100, 10.0), rel=1e-4
    )


def test_a_quantile_below_the_threshold_and_an_infinite_mean_give_no_value() -> None:
    assert math.isnan(gpd.tail_quantile(0.5, 100.0, 0.25, 50.0, 2000, 100))  # below 1 - N_u/n
    assert math.isnan(
        gpd.return_level(0.05, 100.0, 0.25, 50.0, 100, 10.0)
    )  # 100 in 10 years: 0.5 a time
    assert math.isnan(gpd.expected_shortfall(500.0, 100.0, 1.0, 50.0))
    assert math.isnan(gpd.expected_shortfall(500.0, 100.0, 1.4, 50.0))


def test_xi_zero_scale_is_the_mean_excess() -> None:
    # the exponential limit: with xi fixed at 0 the maximum-likelihood scale is the mean excess
    excess = np.array([3.0, 7.0, 11.0, 19.0])
    assert float(excess.mean()) == _closed("xi_zero_scale", "mean_excess")
    scales = np.linspace(8.0, 12.0, 4001)
    loglik = [float(gpd.logpdf(excess, 0.0, s).sum()) for s in scales]
    assert scales[int(np.argmax(loglik))] == pytest.approx(10.0, abs=2e-3)


@pytest.mark.parametrize(
    ("p_values", "k_hat", "next_index"),
    [
        ([0.001, 0.02, 0.05, 0.3, 0.6, 0.8], "forward_stop_rejects_first_three", None),
        ([0.2, 0.3, 0.4], "forward_stop_rejects_none", None),
    ],
)
def test_forward_stop_index_for_given_p_values(p_values, k_hat, next_index) -> None:
    found, path = forward_stop(p_values, 0.10)
    assert found == _closed(k_hat, "k_hat")
    assert found + 1 == _closed(k_hat, "threshold_index_1_based")
    assert path[-1] == pytest.approx(-sum(math.log(1 - p) for p in p_values) / len(p_values))


def test_forward_stop_running_means_and_edges() -> None:
    _, path = forward_stop([0.001, 0.02, 0.05, 0.3, 0.6, 0.8])
    assert path == pytest.approx(
        [0.0010005, 0.0106016, 0.0241655, 0.107293, 0.269092, 0.492483], rel=1e-5
    )
    # k-hat is the largest k whose mean is at most the rate, even after the mean crossed it
    assert forward_stop([0.5, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01], 0.10)[0] == 10
    assert forward_stop([0.01, 0.02], 0.10)[0] == 2  # every candidate rejected
    assert forward_stop([], 0.10)[0] == 0
    assert forward_stop([1.0, 1.0], 0.10)[0] == 0  # a p-value of one never rejects


# ------------------------------------------------------------------ generalised Pareto fit


def test_fit_equals_the_frozen_scipy_fit_of_the_lognormal_sample() -> None:
    sample = gpd_samples()["lognormal"]
    u = float(np.quantile(sample, 0.90))
    assert u == pytest.approx(_frozen("lognormal_sample", "threshold_u"), rel=1e-12)
    excess = sample[sample > u] - u
    assert len(excess) == _frozen("lognormal_sample", "exceedances")
    fit = gpd.fit(excess)
    assert fit.xi == pytest.approx(_frozen("lognormal_sample", "xi"), rel=1e-4)
    assert fit.sigma == pytest.approx(_frozen("lognormal_sample", "sigma"), rel=1e-4)
    assert fit.loglik == pytest.approx(_frozen("lognormal_sample", "loglik"), rel=1e-4)
    assert not fit.boundary


def test_fit_equals_the_frozen_scipy_fit_of_the_generalised_pareto_sample() -> None:
    excess = gpd_samples()["excess"]
    fit = gpd.fit(excess)
    assert fit.xi == pytest.approx(_frozen("gpd_sample", "xi"), rel=1e-4)
    assert fit.sigma == pytest.approx(_frozen("gpd_sample", "sigma"), rel=1e-4)
    assert fit.loglik == pytest.approx(_frozen("gpd_sample", "loglik"), rel=1e-4)
    assert fit.loglik == pytest.approx(gpd.loglik(excess, fit.xi, fit.sigma), rel=1e-12)


@pytest.mark.parametrize("xi", [-0.3, 0.0, 0.4, 1.2])
def test_fit_is_a_maximum_of_the_likelihood_for_light_and_heavy_tails(xi: float) -> None:
    rng = np.random.default_rng(int(100 * xi) + 107)
    excess = np.asarray(stats.genpareto.rvs(xi, scale=500.0, size=300, random_state=rng))
    fit = gpd.fit(excess)
    best = optimize.minimize(
        lambda t: -float(stats.genpareto.logpdf(excess, t[0], scale=math.exp(t[1])).sum()),
        [fit.xi, math.log(fit.sigma)],
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-12},
    )
    assert fit.loglik >= -best.fun - 1e-7  # no better point than ours
    assert fit.xi == pytest.approx(best.x[0], abs=2e-4)


def test_distribution_functions_invert_each_other_for_every_sign_of_xi() -> None:
    q = np.array([0.01, 0.3, 0.9, 0.999])
    for xi in (-0.4, 0.0, 0.7):
        y = gpd.ppf(q, xi, 3.0)
        assert gpd.cdf(y, xi, 3.0) == pytest.approx(q, rel=1e-12)
        assert gpd.sf(y, xi, 3.0) == pytest.approx(1 - q, rel=1e-12)
        assert y == pytest.approx(stats.genpareto.ppf(q, xi, scale=3.0), rel=1e-10)


def test_standard_errors_follow_the_information_of_a_large_sample() -> None:
    excess = gpd_samples()["excess"]
    fit = gpd.fit(excess)
    se_xi, se_sigma = gpd.standard_errors_of(excess, fit)
    # asymptotic standard error of xi for a generalised Pareto: (1 + xi) / sqrt(n)
    assert se_xi == pytest.approx((1 + fit.xi) / math.sqrt(len(excess)), rel=0.15)
    assert se_sigma > 0


def test_profile_interval_is_where_twice_the_loglik_drop_is_the_chi_square_quantile() -> None:
    excess = gpd_samples()["excess"]
    fit = gpd.fit(excess)
    low, high = gpd.profile_interval(excess, fit)
    assert low < fit.xi < high
    for xi in (low, high):  # an independent profile: scipy maximises over sigma at fixed xi

        def negative(s: float, xi: float = xi) -> float:
            return -float(stats.genpareto.logpdf(excess, xi, scale=s).sum())

        profile = optimize.minimize_scalar(
            negative,
            bounds=(fit.sigma * 0.2, fit.sigma * 5.0),
            method="bounded",
            options={"xatol": 1e-9},
        )
        assert 2 * (fit.loglik + profile.fun) == pytest.approx(gpd.CHI2_95, rel=1e-4)


def test_anderson_darling_of_a_hand_sample_against_an_exponential() -> None:
    y = [1.0, 2.0, 3.0]
    big_f = [1.0 - math.exp(-v / 2.0) for v in y]
    n = len(y)
    expected = (
        -n
        - sum(
            (2 * (k + 1) - 1) * (math.log(big_f[k]) + math.log(1.0 - big_f[n - 1 - k]))
            for k in range(n)
        )
        / n
    )
    got = gpd.anderson_darling(np.array([y]), np.array([0.0]), np.array([2.0]))
    assert got[0] == pytest.approx(expected, rel=1e-12)


def test_bootstrap_p_value_accepts_a_generalised_pareto_and_rejects_a_light_tail() -> None:
    excess = gpd_samples()["excess"]
    _, p_good = gpd.bootstrap_p_value(excess, gpd.fit(excess), 100, np.random.default_rng(1))
    assert p_good > 0.05
    rng = np.random.default_rng(2)
    light = 100.0 + np.asarray(stats.weibull_min.rvs(4.0, scale=50.0, size=400, random_state=rng))
    fit = gpd.fit(light)
    _, p_bad = gpd.bootstrap_p_value(light, fit, 100, np.random.default_rng(1))
    assert p_bad <= 0.02
    _, again = gpd.bootstrap_p_value(excess, gpd.fit(excess), 100, np.random.default_rng(1))
    assert again == p_good


# ------------------------------------------------------------------ the threshold rule


def test_candidates_with_fewer_than_min_exceedances_are_not_tried() -> None:
    # sizes 1..247: the 0.80 quantile is 197.8, so 198..247 = 50 sizes are above it
    enough = evt.candidate_thresholds(np.arange(1.0, 248.0), [0.80, 0.90], 50)
    assert enough == [(0.80, pytest.approx(197.8), 50)]
    # sizes 1..246: the 0.80 quantile is 197.0, and 198..246 = 49 sizes are above it
    assert evt.candidate_thresholds(np.arange(1.0, 247.0), [0.80, 0.90], 50) == []
    assert evt.candidate_thresholds(np.array([]), [0.8], 50) == []


def test_enough_exceedances_select_a_threshold_by_forward_stop() -> None:
    rng = np.random.default_rng(21)
    sizes, u0 = spliced_sizes(rng, 1500)
    years = rng.integers(2015, 2025, size=len(sizes))
    cv08 = float(np.quantile(sizes, 0.99))
    result = extreme_values(
        sizes_frame(sizes, years=years), cv08_thresholds={("S", "L"): cv08}, **FAST
    )
    top = result.thresholds.row(0, named=True)
    assert top["status"] == "fitted" and top["exceedances"] >= 50
    table = result.candidates.filter(~pl.col("skipped"))
    # the selected row is the candidate after the k-hat rejected ones, k-hat from its p-values
    k_hat, path = forward_stop(table["p_value"].to_list(), top["fdr_level"])
    assert top["forward_stop_k_hat"] == k_hat
    assert table["selected"].to_list().index(True) == min(k_hat, table.height - 1)
    assert table["rejected_by_forward_stop"].sum() == k_hat
    assert table["forward_stop_mean"].to_list() == pytest.approx(path)
    assert top["threshold"] == pytest.approx(float(np.quantile(sizes, top["quantile"])), rel=1e-12)
    # the fit at the selected threshold is the generalised Pareto fit of its excesses
    excess = sizes[sizes > top["threshold"]] - top["threshold"]
    direct = gpd.fit(excess)
    fit = result.gpd_fit.row(0, named=True)
    assert fit["xi"] == pytest.approx(direct.xi, rel=1e-12)
    assert fit["xi_interval_low"] < fit["xi"] < fit["xi_interval_high"]
    assert fit["modified_scale"] == pytest.approx(direct.sigma - direct.xi * top["threshold"])
    # tail quantiles rise with the probability and agree with the closed form
    tail = result.tail_quantiles
    assert tail["probability"].to_list() == [0.99, 0.995, 0.999]
    assert tail["quantile"].to_list() == sorted(tail["quantile"].to_list())
    expected = gpd.tail_quantile(
        0.995, top["threshold"], direct.xi, direct.sigma, len(sizes), len(excess)
    )
    assert tail["quantile"][1] == pytest.approx(expected, rel=1e-12)
    levels = result.return_levels
    assert levels["return_period"].to_list() == [10, 50, 100, 200]
    assert levels["years_of_data"].to_list() == [10.0] * 4
    assert levels["return_level"].to_list() == sorted(levels["return_level"].to_list())


def test_too_few_exceedances_means_not_run_and_the_cv08_threshold_still_stands() -> None:
    sizes = np.exp(9.0 + np.random.default_rng(3).standard_normal(100))
    cv08 = float(np.quantile(sizes, 0.99))
    result = extreme_values(sizes_frame(sizes), cv08_thresholds={("S", "L"): cv08}, **FAST)
    top = result.thresholds.row(0, named=True)
    assert top["status"] == "not run"
    assert "100 claims" in top["reason"] and "50 excesses" in top["reason"]
    assert result.candidates.is_empty() and result.gpd_fit.is_empty()
    assert [d.code for d in result.diagnostics] == ["NOT_RUN"]
    row = result.threshold_comparison.row(0, named=True)
    assert row["extreme_value_threshold"] is None
    assert row["cv08_threshold"] == cv08
    assert row["claims_at_or_above_cv08"] == 1 and row["claim_share_cv08"] == 0.01
    assert row["note"] == "extreme-value fit not run"


def test_a_candidate_whose_fit_fails_everywhere_also_means_not_run() -> None:
    # equally spaced sizes have a bounded top: xi is -1, below the regular range of the estimator
    result = extreme_values(sizes_frame(np.arange(1.0, 301.0)), **FAST)
    top = result.thresholds.row(0, named=True)
    assert top["status"] == "not run" and "failed at every candidate" in top["reason"]
    assert result.candidates.is_empty() or result.candidates["skipped"].all()
    assert any(d.code == "CANDIDATE_SKIPPED" for d in result.diagnostics)


def test_all_candidates_rejected_shows_the_highest_threshold_with_a_warning(monkeypatch) -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1500)
    real = gpd.bootstrap_p_value
    monkeypatch.setattr(
        evt.gpd,
        "bootstrap_p_value",
        lambda excess, fitted, n_boot, rng: (real(excess, fitted, 5, rng)[0], 0.001),
    )
    result = extreme_values(sizes_frame(sizes), **FAST)
    top = result.thresholds.row(0, named=True)
    table = result.candidates.filter(~pl.col("skipped"))
    assert top["forward_stop_k_hat"] == table.height
    assert top["quantile"] == table["quantile"].max()  # the highest candidate
    assert "rejected" in top["reason"]
    assert any(d.code == "ALL_REJECTED" for d in result.diagnostics)


def test_threshold_comparison_counts_claims_and_incurred_above_each_threshold() -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1500)
    cv08 = float(np.quantile(sizes, 0.99))
    result = extreme_values(sizes_frame(sizes), cv08_thresholds={("S", "L"): cv08}, **FAST)
    row = result.threshold_comparison.row(0, named=True)
    u = row["extreme_value_threshold"]
    assert row["claims_above_extreme_value"] == int(np.sum(sizes > u))  # an excess is above u
    assert row["claim_share_extreme_value"] == pytest.approx(np.mean(sizes > u))
    assert row["incurred_share_extreme_value"] == pytest.approx(
        sizes[sizes > u].sum() / sizes.sum()
    )
    assert row["claims_at_or_above_cv08"] == int(np.sum(sizes >= cv08))  # LARGE is at or above
    assert row["incurred_share_cv08"] == pytest.approx(sizes[sizes >= cv08].sum() / sizes.sum())
    assert row["incurred_share_extreme_value"] > row["incurred_share_cv08"]


def test_without_a_cv08_threshold_the_comparison_still_reports_the_selected_one() -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1500)
    result = extreme_values(sizes_frame(sizes), **FAST)
    row = result.threshold_comparison.row(0, named=True)
    assert row["extreme_value_threshold"] is not None and row["cv08_threshold"] is None


# ------------------------------------------------------------------ groups, seeds, diagnostics


def test_events_are_one_size_each_and_results_do_not_depend_on_row_order() -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1200)
    codes: list[str | None] = [None] * len(sizes)
    codes[0] = codes[1] = codes[2] = "STORM"
    frame = sizes_frame(sizes, event_codes=codes, years=rng.integers(2015, 2025, len(sizes)))
    first = extreme_values(frame, **FAST)
    second = extreme_values(frame.sample(fraction=1.0, shuffle=True, seed=1), **FAST)
    assert (
        first.thresholds.row(0, named=True)["claims"] == len(sizes) - 2
    )  # three claims, one event
    assert first.thresholds["events"][0] == 1
    assert first.candidates.equals(second.candidates)
    assert first.gpd_fit.equals(second.gpd_fit)


def test_the_seed_is_recorded_and_changes_only_the_bootstrap() -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1200)
    frame = sizes_frame(sizes)
    one = extreme_values(frame, seed=1, **FAST)
    again = extreme_values(frame, seed=1, **FAST)
    two = extreme_values(frame, seed=2, **FAST)
    assert one.candidates.equals(again.candidates)
    assert one.candidates["xi"].to_list() == two.candidates["xi"].to_list()
    assert one.candidates["p_value"].to_list() != two.candidates["p_value"].to_list()
    assert one.randomness() == [
        {"method": "MT18", "seed": 1, "purpose": one.randomness()[0]["purpose"]}
    ]


def test_yearly_exceedance_counts_and_the_overdispersion_warning() -> None:
    rng = np.random.default_rng(21)
    sizes, u0 = spliced_sizes(rng, 1500)
    spread = rng.integers(2015, 2025, size=len(sizes))
    clustered = np.where(sizes > u0, 2015, spread)  # every large claim in one year
    calm = extreme_values(sizes_frame(sizes, years=spread), **FAST)
    loud = extreme_values(sizes_frame(sizes, years=clustered), **FAST)
    assert calm.yearly.height == 10
    assert calm.yearly["exceedances"].sum() == calm.thresholds["exceedances"][0]
    assert calm.yearly_summary["dispersion_p_value"][0] > 0.01
    assert not any(d.code == "OVERDISPERSED_EXCEEDANCES" for d in calm.diagnostics)
    assert any(d.code == "OVERDISPERSED_EXCEEDANCES" for d in loud.diagnostics)


def test_mean_excess_and_the_excess_plot_are_data_for_the_report() -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1500)
    result = extreme_values(sizes_frame(sizes), **FAST)
    me = result.mean_excess
    row = me.row(0, named=True)
    u = float(np.quantile(sizes, row["quantile"]))
    assert row["threshold"] == pytest.approx(u, rel=1e-12)
    assert row["mean_excess"] == pytest.approx(float((sizes[sizes > u] - u).mean()), rel=1e-12)
    assert min(me["exceedances"].to_list()) >= evt.MEAN_EXCESS_MIN
    plot = result.excess_plot
    assert plot.height == min(200, result.thresholds["exceedances"][0])
    assert plot["empirical_excess"].to_list() == sorted(plot["empirical_excess"].to_list())
    assert plot["fitted_excess"].to_list() == sorted(plot["fitted_excess"].to_list())


def test_no_origin_years_means_no_return_levels() -> None:
    rng = np.random.default_rng(21)
    sizes, _ = spliced_sizes(rng, 1200)
    result = extreme_values(sizes_frame(sizes), **FAST)
    assert result.return_levels.is_empty()
    assert any(d.code == "NO_YEARS" for d in result.diagnostics)
    with_years = extreme_values(sizes_frame(sizes), years=20.0, **FAST)
    assert with_years.return_levels["years_of_data"].to_list() == [20.0] * 4


def test_the_true_quantile_of_the_spliced_model_is_its_closed_form() -> None:
    # the reference of the calibration test (behind ACTUARYCANARY_MONTE_CARLO=1):
    # P(X > x) = tail_share x generalised Pareto survival of the excess
    u0, xi, scale, share = 20000.0, 0.3, 2e4, 0.1
    x = spliced_quantile(0.995, u0, share, xi, scale)
    assert share * float(stats.genpareto.sf(x - u0, xi, scale=scale)) == pytest.approx(
        0.005, rel=1e-12
    )
    sizes, start = spliced_sizes(np.random.default_rng(5), 200_000, share, xi, scale)
    assert float(np.mean(sizes > start)) == pytest.approx(share, abs=0.002)
    assert float(np.mean(sizes > spliced_quantile(0.99, start, share, xi, scale))) == pytest.approx(
        0.01, abs=0.001
    )


def test_bad_options_are_refused() -> None:
    frame = sizes_frame(np.arange(1.0, 400.0))
    with pytest.raises(ValueError, match="candidate_quantiles"):
        extreme_values(frame, candidate_quantiles=[0.8, 1.0])
    with pytest.raises(ValueError, match="candidate_quantiles"):
        extreme_values(frame, candidate_quantiles=[])
    with pytest.raises(ValueError, match="return_periods"):
        extreme_values(frame, return_periods=[10, 0])
    with pytest.raises(ValueError, match="min_exceedances"):
        extreme_values(frame, min_exceedances=5)
