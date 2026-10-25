"""MT17 severity distribution fitting: fixtures, the frozen scipy references, goodness of fit,
selection, claims used, truncation, limits and the trend of sizes.

Spec IDs proved: MT17.
"""

import math
from typing import Any

import numpy as np
import polars as pl
import pytest
from scipy import special, stats

from actuarycanary.methods.severity import families as fam
from actuarycanary.methods.severity import fitting, gof
from actuarycanary.methods.severity.fitting import NO_FAMILY_FITS, SELECTED_BY_AIC, fit_severity
from tests.benchmarks.load import load_reference
from tests.methods.severity.helpers import CLOSED, NIL, OPEN, severity_samples, sizes_frame

REFERENCE = load_reference("MT17-severity-fits")["values"]
SAMPLE_NAMES = ("lognormal", "gamma", "weibull", "pareto")
FAST: dict[str, Any] = {"gof_bootstrap": 40}  # bootstrap samples in the fast tests


def _frozen(quantity: str, key: str) -> float:
    return REFERENCE[(quantity, key)]["value"]


# ------------------------------------------------------------------ fixtures


def test_lognormal_fit_is_the_mean_and_standard_deviation_of_the_logs() -> None:
    x = severity_samples()["lognormal"]
    est = fam.estimate(fam.LOGNORMAL, x)
    assert est.a == pytest.approx(float(np.mean(np.log(x))), rel=1e-12)
    assert est.b == pytest.approx(float(np.std(np.log(x))), rel=1e-12)  # divisor n
    assert est.a == pytest.approx(_frozen("closed_form_lognormal", "mu"), rel=1e-9)
    assert est.b == pytest.approx(_frozen("closed_form_lognormal", "sigma"), rel=1e-9)


def test_exponential_is_gamma_with_shape_one_and_its_maximum_is_the_mean() -> None:
    x = severity_samples()["gamma"]
    mean = float(x.mean())
    assert mean == pytest.approx(_frozen("sample_mean_gamma", "mean"), rel=1e-12)

    def loglik(scale: float) -> float:
        return float(fam.logpdf(fam.GAMMA, x, 1.0, scale).sum())

    assert loglik(mean) > loglik(mean * 1.001)
    assert loglik(mean) > loglik(mean * 0.999)
    # the first-order condition of the exponential likelihood holds at the mean
    assert float(np.sum(x / mean**2 - 1.0 / mean)) == pytest.approx(0.0, abs=1e-9)


def test_truncated_lognormal_likelihood_of_a_hand_sample() -> None:
    x, d, mu, sigma = [2.0, 3.0, 5.0, 8.0, 13.0], 1.5, 1.2, 0.8
    phi = 0.5 * math.erfc(-((math.log(d) - mu) / sigma) / math.sqrt(2.0))  # P(Z <= z)
    expected = sum(
        -math.log(v)
        - math.log(sigma)
        - 0.5 * math.log(2.0 * math.pi)
        - (math.log(v) - mu) ** 2 / (2.0 * sigma**2)
        for v in x
    ) - len(x) * math.log(1.0 - phi)
    assert fam.loglik(fam.LOGNORMAL, np.array(x), mu, sigma, d) == pytest.approx(
        expected, rel=1e-12
    )


def test_truncated_pareto_likelihood_of_a_hand_sample() -> None:
    # survival (1 + x / theta)^-alpha, so P(X > d) is closed and the likelihood is a sum of logs
    x, d, alpha, theta = [2.0, 3.0, 5.0, 8.0, 13.0], 1.5, 2.5, 4.0
    expected = sum(
        math.log(alpha) - math.log(theta) - (alpha + 1.0) * math.log1p(v / theta) for v in x
    ) + len(x) * alpha * math.log1p(d / theta)
    assert fam.loglik(fam.PARETO, np.array(x), alpha, theta, d) == pytest.approx(
        expected, rel=1e-12
    )


def test_truncated_fit_conditions_on_the_truncation_point() -> None:
    rng = np.random.default_rng(11)
    x = np.exp(10.0 + 1.0 * rng.standard_normal(3000))
    d = math.exp(9.7)
    kept = x[x > d]
    truncated = fam.estimate(fam.LOGNORMAL, kept, d)
    naive = fam.estimate(fam.LOGNORMAL, kept)
    assert truncated.converged
    assert abs(truncated.a - 10.0) < 3 * truncated.a_se
    assert abs(truncated.b - 1.0) < 3 * truncated.b_se
    assert abs(naive.a - 10.0) > 3 * naive.a_se  # ignoring the truncation biases the fit


def test_standard_errors_of_the_lognormal_are_the_closed_forms() -> None:
    x = severity_samples()["lognormal"]
    est = fam.estimate(fam.LOGNORMAL, x)
    assert est.a_se == pytest.approx(est.b / math.sqrt(len(x)), rel=1e-5)
    assert est.b_se == pytest.approx(est.b / math.sqrt(2.0 * len(x)), rel=1e-5)


def test_standard_errors_of_the_gamma_are_the_inverse_information() -> None:
    x = severity_samples()["gamma"]
    est = fam.estimate(fam.GAMMA, x)
    n, a, theta = len(x), est.a, est.b
    information = n * np.array(
        [[special.polygamma(1, a), 1.0 / theta], [1.0 / theta, a / theta**2]]
    )
    se = np.sqrt(np.diag(np.linalg.inv(information)))
    assert est.a_se == pytest.approx(se[0], rel=1e-5)
    assert est.b_se == pytest.approx(se[1], rel=1e-5)


# ------------------------------------------------------------------ frozen scipy references


@pytest.mark.parametrize("sample", SAMPLE_NAMES)
def test_every_family_on_every_sample_matches_the_frozen_scipy_fit(sample: str) -> None:
    x = severity_samples()[sample]
    aics = []
    for family in SAMPLE_NAMES:
        est = fam.estimate(family, x)
        key = f"{sample}_sample/{family}"
        assert est.loglik == pytest.approx(_frozen("loglik", key), rel=1e-4)
        assert est.aic == pytest.approx(_frozen("aic", key), rel=1e-4)
        aics.append(est.aic)
        if not est.converged:  # a Pareto II whose shape runs to infinity: scipy's pair is arbitrary
            assert family == fam.PARETO and sample in ("gamma", "weibull")
            continue
        if family == fam.LOGNORMAL:
            assert est.b == pytest.approx(_frozen("mle_sigma", key), rel=1e-4)
            assert math.exp(est.a) == pytest.approx(_frozen("mle_exp_mu", key), rel=1e-4)
        else:
            first, second = {"gamma": ("shape", "scale"), "weibull": ("shape", "scale")}.get(
                family, ("alpha", "theta")
            )
            assert est.a == pytest.approx(_frozen(f"mle_{first}", key), rel=1e-4)
            assert est.b == pytest.approx(_frozen(f"mle_{second}", key), rel=1e-4)
    assert int(np.argmin(aics)) == _frozen("lowest_aic_family", f"{sample}_sample")


def test_a_pareto_whose_shape_runs_to_infinity_is_not_converged_and_says_so() -> None:
    frame = sizes_frame(severity_samples()["gamma"])
    result = fit_severity(frame, **FAST)
    pareto = result.fits.filter(pl.col("family") == "pareto").row(0, named=True)
    assert pareto["converged"] is False
    assert pareto["aic_rank"] is None
    assert pareto["ad_p"] is None
    assert any(
        d.code == "NO_CONVERGENCE" and "tends to infinity" in d.message for d in result.diagnostics
    )


@pytest.mark.parametrize(
    ("family", "a", "b"),
    [
        (fam.LOGNORMAL, 10.0, 1.2),
        (fam.GAMMA, 2.5, 4000.0),
        (fam.WEIBULL, 1.5, 8000.0),
        (fam.PARETO, 3.0, 50000.0),
    ],
)
def test_limited_expected_value_is_the_integral_of_the_survival_function(
    family: str, a: float, b: float
) -> None:
    limit = 30000.0
    grid = np.linspace(0.0, limit, 400_001)
    numeric = float(np.trapezoid(fam.sf(family, grid, a, b), grid))
    assert fam.limited_expected_value(family, limit, a, b) == pytest.approx(numeric, rel=1e-7)
    q = float(fam.ppf(family, 0.9, a, b))
    assert float(fam.cdf(family, np.array(q), a, b)) == pytest.approx(0.9, rel=1e-12)


def test_pareto_with_shape_one_has_a_logarithmic_limited_expected_value() -> None:
    assert fam.limited_expected_value(fam.PARETO, 3000.0, 1.0, 1000.0) == pytest.approx(
        1000.0 * math.log(4.0), rel=1e-12
    )
    assert not fam.mean_is_finite(fam.PARETO, 1.0)


# ------------------------------------------------------------------ goodness of fit


def test_statistics_of_a_hand_sample_against_an_exponential() -> None:
    x = [1.0, 2.0, 3.0]
    big_f = [1.0 - math.exp(-v / 2.0) for v in x]  # gamma with shape 1 and scale 2
    n = len(x)
    d = max(max((i + 1) / n - big_f[i], big_f[i] - i / n) for i in range(n))
    a2 = (
        -n
        - sum(
            (2 * (k + 1) - 1) * (math.log(big_f[k]) + math.log(1.0 - big_f[n - 1 - k]))
            for k in range(n)
        )
        / n
    )
    ks, ad = gof.statistics(fam.GAMMA, np.array([x]), np.array([1.0]), np.array([2.0]))
    assert ks[0] == pytest.approx(d, rel=1e-12)
    assert ad[0] == pytest.approx(a2, rel=1e-12)


def test_statistics_under_truncation_use_the_conditional_distribution_function() -> None:
    x = np.array([2.0, 3.0, 5.0])
    d, scale = 1.0, 2.0  # exponential: the conditional survival is exp(-(x - d) / scale)
    conditional = 1.0 - np.exp(-(x - d) / scale)
    ks, _ = gof.statistics(fam.GAMMA, x[None, :], np.array([1.0]), np.array([scale]), d)
    expected = max(max((i + 1) / 3 - conditional[i], conditional[i] - i / 3) for i in range(3))
    assert ks[0] == pytest.approx(expected, rel=1e-12)


def test_true_family_is_not_rejected_and_a_wrong_one_is() -> None:
    x = severity_samples()["lognormal"]
    rng = np.random.default_rng(5)
    a, b, _ = fam.mle(fam.LOGNORMAL, x)
    right = gof.goodness_of_fit(fam.LOGNORMAL, x, a, b, 60, rng)
    a2, b2, _ = fam.mle(fam.GAMMA, x)
    wrong = gof.goodness_of_fit(fam.GAMMA, x, a2, b2, 60, np.random.default_rng(5))
    assert right.ad_p > 0.05 and right.ks_p > 0.05
    assert wrong.ad_p == pytest.approx(1 / 61)  # the observed statistic exceeds every bootstrap one
    assert right.n_boot == 60 and right.n_used == len(x)


def test_bootstrap_p_values_repeat_with_the_seed_and_move_with_another() -> None:
    x = severity_samples()["gamma"]
    a, b, _ = fam.mle(fam.WEIBULL, x)
    first = gof.goodness_of_fit(fam.WEIBULL, x, a, b, 60, np.random.default_rng(1))
    again = gof.goodness_of_fit(fam.WEIBULL, x, a, b, 60, np.random.default_rng(1))
    other = gof.goodness_of_fit(fam.WEIBULL, x, a, b, 60, np.random.default_rng(2))
    assert first == again
    assert (first.ad, first.ks) == (other.ad, other.ks)  # the statistics do not depend on the seed
    assert first.ad_p != other.ad_p or first.ks_p != other.ks_p


def test_plot_data_hold_the_order_statistics_when_points_equal_claims() -> None:
    x = np.array([5.0, 1.0, 3.0, 2.0, 4.0])
    a, b, _ = fam.mle(fam.GAMMA, x)
    data = gof.plot_data(fam.GAMMA, x, a, b, points=5)
    assert data["empirical_quantile"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert data["probability"].tolist() == pytest.approx([0.1, 0.3, 0.5, 0.7, 0.9])
    assert data["fitted_quantile"][2] == pytest.approx(float(fam.ppf(fam.GAMMA, 0.5, a, b)))
    assert data["empirical_survival"].tolist() == pytest.approx([0.9, 0.7, 0.5, 0.3, 0.1])


# ------------------------------------------------------------------ selection and tables


@pytest.mark.parametrize("sample", SAMPLE_NAMES)
def test_the_family_that_made_the_sample_is_selected(sample: str) -> None:
    result = fit_severity(sizes_frame(severity_samples()[sample]), **FAST)
    chosen = result.selected.row(0, named=True)
    assert chosen["family"] == sample
    assert chosen["why"] == SELECTED_BY_AIC
    assert chosen["claims"] == 500
    fits = result.fits.filter(pl.col("family") == sample).row(0, named=True)
    assert fits["selected"] and not fits["rejected"] and fits["aic_rank"] == 1


def test_fits_carry_aic_bic_ranks_statistics_and_the_gof_sample_size() -> None:
    result = fit_severity(sizes_frame(severity_samples()["lognormal"]), **FAST)
    row = result.fits.filter(pl.col("family") == "lognormal").row(0, named=True)
    n = 500
    assert row["aic"] == pytest.approx(4 - 2 * row["loglik"], rel=1e-12)
    assert row["bic"] == pytest.approx(2 * math.log(n) - 2 * row["loglik"], rel=1e-12)
    assert row["gof_claims"] == n and row["gof_bootstrap"] == 40
    assert row["bic_rank"] == 1
    assert sorted(result.fits["aic_rank"].drop_nulls().to_list()) == [1, 2, 3, 4]
    params = result.parameters.filter(pl.col("family") == "lognormal")
    assert params["parameter"].to_list() == ["mu", "sigma"]
    assert params["std_error"].null_count() == 0
    assert result.plots.filter(pl.col("family") == "lognormal").height == 200


def test_the_lowest_aic_among_the_families_not_rejected_is_selected(monkeypatch) -> None:
    p_values = {"lognormal": 0.01, "gamma": 0.01, "weibull": 0.01, "pareto": 0.50}
    real = gof.goodness_of_fit

    def forced(family, x, a, b, n_boot, rng, truncation=0.0):
        found = real(family, x, a, b, 5, rng, truncation)
        return gof.Gof(found.ks, found.ad, p_values[family], p_values[family], found.n_used, 5)

    monkeypatch.setattr(fitting.gof, "goodness_of_fit", forced)
    result = fit_severity(sizes_frame(severity_samples()["lognormal"]), **FAST)
    chosen = result.selected.row(0, named=True)
    # lognormal has the lowest AIC but is rejected here, so Pareto (next lowest AIC) wins
    assert chosen["family"] == "pareto" and chosen["why"] == SELECTED_BY_AIC
    rejected = result.fits.filter(pl.col("rejected"))["family"].to_list()
    assert sorted(rejected) == ["gamma", "lognormal", "weibull"]


def test_when_every_family_is_rejected_the_lowest_aic_is_labelled_no_family_fits(
    monkeypatch,
) -> None:
    real = gof.goodness_of_fit

    def forced(family, x, a, b, n_boot, rng, truncation=0.0):
        found = real(family, x, a, b, 5, rng, truncation)
        return gof.Gof(found.ks, found.ad, 0.01, 0.01, found.n_used, 5)

    monkeypatch.setattr(fitting.gof, "goodness_of_fit", forced)
    result = fit_severity(sizes_frame(severity_samples()["lognormal"]), **FAST)
    chosen = result.selected.row(0, named=True)
    assert chosen["family"] == "lognormal" and chosen["why"] == NO_FAMILY_FITS
    assert any(d.code == "NO_FAMILY_FITS" for d in result.diagnostics)


def test_a_group_with_fewer_than_min_claims_is_not_fitted_with_the_count() -> None:
    frame = pl.concat(
        [
            sizes_frame(severity_samples()["gamma"][:49], line="SMALL", prefix="A"),
            sizes_frame(severity_samples()["gamma"][:50], line="EXACT", prefix="B"),
        ]
    )
    result = fit_severity(frame, **FAST)
    small = result.groups.filter(pl.col("line") == "SMALL").row(0, named=True)
    assert small["status"] == "not fitted" and small["reason"] == "49 claims, fewer than 50"
    assert result.selected.filter(pl.col("line") == "SMALL")["family"][0] is None
    assert result.fits.filter(pl.col("line") == "SMALL").is_empty()
    assert result.groups.filter(pl.col("line") == "EXACT")["status"][0] == "fitted"
    assert [d.code for d in result.diagnostics if d.target == "S / SMALL"] == ["NOT_FITTED"]


def test_goodness_of_fit_runs_on_a_seeded_subsample_of_large_groups() -> None:
    x = severity_samples()["lognormal"]
    options: dict[str, Any] = {"gof_max_claims": 200, "gof_bootstrap": 30}
    first = fit_severity(sizes_frame(x), **options)
    again = fit_severity(sizes_frame(x), **options)
    other = fit_severity(sizes_frame(x), seed=2, **options)
    row = first.fits.filter(pl.col("family") == "lognormal").row(0, named=True)
    assert row["gof_claims"] == 200 and row["claims"] == 500
    # the likelihood, the AIC and the standard errors use every claim
    assert row["loglik"] == pytest.approx(fam.estimate(fam.LOGNORMAL, x).loglik, rel=1e-12)
    assert first.fits.equals(again.fits)
    assert first.fits["ks"].to_list() != other.fits["ks"].to_list()  # another subsample
    assert first.seed == 1 and other.seed == 2
    assert first.randomness()[0]["seed"] == 1


def test_results_do_not_depend_on_the_order_of_the_rows() -> None:
    frame = sizes_frame(severity_samples()["weibull"][:120])
    shuffled = frame.sample(fraction=1.0, shuffle=True, seed=3)
    first = fit_severity(frame, **FAST)
    second = fit_severity(shuffled, **FAST)
    assert first.fits.equals(second.fits)
    assert first.plots.equals(second.plots)


# ------------------------------------------------------------------ claims used, truncation


def _mixed_frame() -> pl.DataFrame:
    rng = np.random.default_rng(2)
    closed = np.exp(8.0 + 0.9 * rng.standard_normal(80))
    open_ = np.exp(9.0 + 0.9 * rng.standard_normal(30))
    nil = np.zeros(10)
    catastrophe = np.full(5, 1e6)
    return pl.concat(
        [
            sizes_frame(closed, status=CLOSED, prefix="A"),
            sizes_frame(open_, status=OPEN, prefix="B"),
            sizes_frame(nil, status=NIL, prefix="C"),
            sizes_frame(catastrophe, status=CLOSED, event_codes=["STORM"] * 5, prefix="D"),
        ]
    )


def test_closed_claims_by_default_and_every_non_nil_claim_on_request() -> None:
    frame = _mixed_frame()
    closed = fit_severity(frame, **FAST)
    everything = fit_severity(frame, claims_used="all_non_nil", **FAST)
    assert closed.groups["claims"][0] == 80  # nil, open and catastrophe claims are out
    assert everything.groups["claims"][0] == 110
    assert closed.groups["claims_used"][0] == "closed"
    keep_catastrophes = fit_severity(
        frame, claims_used="closed", exclude_catastrophes=False, **FAST
    )
    assert keep_catastrophes.groups["claims"][0] == 85


def test_the_two_claim_sets_can_be_compared() -> None:
    both = fitting.compare_claim_sets(_mixed_frame(), **FAST)
    assert set(both) == {"closed", "all_non_nil"}
    assert both["closed"].groups["claims"][0] < both["all_non_nil"].groups["claims"][0]
    closed_mu = both["closed"].parameters.filter(pl.col("family") == "lognormal")["estimate"][0]
    all_mu = both["all_non_nil"].parameters.filter(pl.col("family") == "lognormal")["estimate"][0]
    assert all_mu > closed_mu  # open claims are larger in this fixture


def test_a_truncation_point_leaves_out_small_claims_and_conditions_the_likelihood() -> None:
    x = severity_samples()["lognormal"]
    d = float(np.quantile(x, 0.2))
    result = fit_severity(sizes_frame(x), truncation_point=d, candidates=["lognormal"], **FAST)
    kept = x[x > d]
    expected = fam.estimate(fam.LOGNORMAL, kept, d)
    row = result.fits.row(0, named=True)
    assert row["claims"] == len(kept)
    assert row["loglik"] == pytest.approx(expected.loglik, rel=1e-9)
    assert result.groups["truncation_point"][0] == d


def test_an_unknown_family_and_bad_limits_are_refused() -> None:
    frame = sizes_frame(severity_samples()["gamma"])
    with pytest.raises(fam.FamilyError, match="unknown family"):
        fit_severity(frame, candidates=["normal"])
    with pytest.raises(ValueError, match="limits must be positive"):
        fit_severity(frame, limits=[1000, 0])
    with pytest.raises(ValueError, match="truncation_point"):
        fit_severity(frame, truncation_point=-1.0)


# ------------------------------------------------------------------ outputs


def test_quantiles_and_layer_costs_of_the_selected_family() -> None:
    x = severity_samples()["pareto"]
    result = fit_severity(sizes_frame(x), limits=[20000, 100000], **FAST)
    est = fam.estimate(fam.PARETO, x)
    quantiles = result.quantiles
    assert quantiles["probability"].to_list() == [0.5, 0.75, 0.9, 0.95, 0.99, 0.995]
    assert quantiles["quantile"][4] == pytest.approx(
        est.b * (0.01 ** (-1.0 / est.a) - 1.0), rel=1e-9
    )
    layers = result.limited_expected_values
    assert layers["layer_retention"].to_list() == [0.0, 20000.0, 100000.0]
    assert layers["limit"].to_list() == [20000.0, 100000.0, None]
    mean = est.b / (est.a - 1.0)
    assert layers["layer_cost"].sum() == pytest.approx(mean, rel=1e-9)  # layers add up to the mean
    assert layers["limited_expected_value"][0] == pytest.approx(
        fam.limited_expected_value(fam.PARETO, 20000.0, est.a, est.b), rel=1e-12
    )
    assert layers["survival_at_limit"][0] == pytest.approx(
        float(fam.sf(fam.PARETO, np.array(20000.0), est.a, est.b)), rel=1e-12
    )


def test_an_infinite_mean_is_warned_about_and_only_limited_values_are_given() -> None:
    rng = np.random.default_rng(8)
    x = np.asarray(stats.lomax.rvs(0.8, scale=1000.0, size=400, random_state=rng))
    result = fit_severity(sizes_frame(x), candidates=["pareto"], limits=[5000], **FAST)
    last = result.limited_expected_values.row(1, named=True)
    assert last["limit"] is None
    assert last["limited_expected_value"] is None or math.isnan(last["limited_expected_value"])
    assert result.limited_expected_values["layer_cost"][0] > 0
    assert any(d.code == "INFINITE_MEAN" for d in result.diagnostics)


def test_sizes_by_origin_year_show_a_trend_and_warn_when_it_is_clear() -> None:
    rng = np.random.default_rng(4)
    years = np.repeat(np.arange(2015, 2025), 60)
    flat = np.exp(9.0 + 0.8 * rng.standard_normal(len(years)))
    trending = flat * 1.08 ** (years - 2015)
    quiet = fit_severity(sizes_frame(flat, years=years), candidates=["lognormal"], **FAST)
    loud = fit_severity(sizes_frame(trending, years=years), candidates=["lognormal"], **FAST)
    assert quiet.trend.height == 10 and quiet.trend["claims"].to_list() == [60] * 10
    assert not any(d.code == "SEVERITY_TREND" for d in quiet.diagnostics)
    summary = loud.trend_summary.row(0, named=True)
    assert summary["annual_change"] == pytest.approx(0.08, abs=0.02)
    assert summary["p_value"] < 0.01
    assert any(d.code == "SEVERITY_TREND" for d in loud.diagnostics)


def test_thin_evidence_is_warned_when_fewer_than_eight_origin_years() -> None:
    years = np.repeat(np.arange(2021, 2025), 30)
    x = severity_samples()["gamma"][:120]
    result = fit_severity(sizes_frame(x, years=years), candidates=["gamma"], **FAST)
    assert any(d.code == "THIN_EVIDENCE" for d in result.diagnostics)
