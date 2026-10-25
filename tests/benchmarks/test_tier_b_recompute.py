"""Tier B references recomputed from their own input files, with no reference package.

Spec IDs proved: MT11, MT12, MT13, MT14, MT15, MT16, MT17, MT18, MT19, MT20, MT21, MT22.

A frozen number is only a reference if it can be rebuilt from the inputs next to it. The tests below
do that with plain Python, numpy and scipy (the toolchain), so a wrong freeze, a hand edit or a
changed input shows up here. They do not build the platform's methods: P24, P25, P30 and P33 prove
their methods against these references.
"""

import math
from fractions import Fraction as Fr
from pathlib import Path

import numpy as np
import pytest
from scipy import optimize, stats

from tests.benchmarks.load import (
    load_reference,
    load_table,
    load_triangle,
    reference_series,
)


def _ref(name: str):
    ref = load_reference(name)
    return ref["folder"], ref["values"]


def _information(name: str) -> dict[tuple[str, str], float]:
    """Variants the specs dropped, kept in the manifest as information (decisions 0607, 0608)."""
    rows = load_reference(name)["manifest"].get("information", [])
    return {(r["quantity"], str(r["key"])): r["value"] for r in rows}


def _value(values, quantity: str, key) -> float:
    return values[(quantity, str(key))]["value"]


def _close(values, quantity: str, key, expected: float, rel: float = 1e-9) -> None:
    row = values[(quantity, str(key))]
    assert expected == pytest.approx(row["value"], rel=max(rel, 1e-15)), (quantity, key)


def _array(path: Path) -> np.ndarray:
    tri = load_triangle(path)
    return np.array([[np.nan if v is None else v for v in r] for r in tri["values"]])


def _volume_factors(tri: np.ndarray) -> np.ndarray:
    n = tri.shape[0]
    return np.array(
        [np.nansum(tri[: n - 1 - j, j + 1]) / np.nansum(tri[: n - 1 - j, j]) for j in range(n - 1)]
    )


def _cdf_by_origin(tri: np.ndarray) -> np.ndarray:
    n = tri.shape[0]
    f = _volume_factors(tri)
    return np.array([np.prod(f[n - 1 - i :]) for i in range(n)])


def _latest(tri: np.ndarray) -> np.ndarray:
    n = tri.shape[0]
    return np.array([tri[i, n - 1 - i] for i in range(n)])


# ------------------------------------------------------------------ MT11


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_mt11_scale_parameter_and_residuals(name: str) -> None:
    folder, values = _ref(f"MT11-odp-bootstrap-{name}")
    tri = _array(folder / "triangle.csv")
    n = tri.shape[0]
    cum_fit = np.full((n, n), np.nan)
    f = _volume_factors(tri)
    for i in range(n):
        last = n - 1 - i
        cum_fit[i, last] = tri[i, last]
        for j in range(last - 1, -1, -1):
            cum_fit[i, j] = cum_fit[i, j + 1] / f[j]
    cells = n * (n + 1) // 2
    params = 2 * n - 1
    rows = load_table(folder / "residuals.csv")
    assert len(rows) == cells
    first_origin = load_triangle(folder / "triangle.csv")["origins"][0]
    sum_sq = 0.0
    zero_cells = 0
    for row in rows:
        i, j = int(row["origin"]) - first_origin, int(row["age"]) // 12 - 1
        obs = tri[i, j] - (tri[i, j - 1] if j else 0.0)
        fit = cum_fit[i, j] - (cum_fit[i, j - 1] if j else 0.0)
        unscaled = (obs - fit) / math.sqrt(fit)
        assert float(row["unscaled_residual"]) == pytest.approx(unscaled, rel=1e-9, abs=1e-9)
        adjusted = unscaled * math.sqrt(cells / (cells - params))
        assert float(row["adjusted_residual"]) == pytest.approx(adjusted, rel=1e-9, abs=1e-9)
        zero_cells += abs(unscaled) < 1e-9
        sum_sq += unscaled**2
    assert zero_cells == 2, "the two cells fitted exactly leave the resampling pool"
    phi = sum_sq / (cells - params)
    _close(values, "deterministic", "scale_parameter_phi", phi)
    _close(
        values,
        "deterministic",
        "chain_ladder_reserve",
        float(np.sum(_latest(tri) * (_cdf_by_origin(tri) - 1))),
    )


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_mt11_simulation_summaries_are_consistent(name: str) -> None:
    _, values = _ref(f"MT11-odp-bootstrap-{name}")
    reserve = _value(values, "deterministic", "chain_ladder_reserve")
    phi = _value(values, "deterministic", "scale_parameter_phi")
    for kind in ("parameter_error_only", "with_process_error"):
        q = f"simulation_{kind}_total_reserve"
        # spec benchmark: simulated mean within 2 per cent of the chain-ladder reserve
        assert _value(values, q, "mean") == pytest.approx(reserve, rel=0.02)
        assert _value(values, q, "p50") < _value(values, q, "p75")
        assert _value(values, q, "p75") < _value(values, q, "p95") < _value(values, q, "p99.5")
    q_param = "simulation_parameter_error_only_total_reserve"
    q_full = "simulation_with_process_error_total_reserve"
    sd_param = _value(values, q_param, "sd")
    mean_param = _value(values, q_param, "mean")
    analytic = math.sqrt(sd_param**2 + phi * mean_param)
    _close(values, q_full, "sd_analytic", analytic)
    tol = values[(q_full, "sd")]["rel_tol"]
    assert _value(values, q_full, "sd") == pytest.approx(analytic, rel=tol)
    assert _value(values, q_full, "sd") > sd_param


# ------------------------------------------------------------------ MT12


def test_mt12_munich_reference_is_consistent_with_separate_chain_ladders() -> None:
    folder, values = _ref("MT12-munich-chain-ladder-mcl")
    paid, incurred = _array(folder / "paid.csv"), _array(folder / "incurred.csv")
    origins = load_triangle(folder / "paid.csv")["origins"]
    for label, tri in (("paid", paid), ("incurred", incurred)):
        ult = _latest(tri) * _cdf_by_origin(tri)
        for origin, u in zip(origins, ult, strict=True):
            _close(values, f"chain_ladder_{label}_ultimate", origin, float(u), 1e-6)
    for origin in origins:
        ratio = _value(values, "munich_paid_ultimate", origin) / _value(
            values, "munich_incurred_ultimate", origin
        )
        _close(values, "munich_paid_to_incurred_ratio", origin, ratio)
    # Munich moves the two ultimates towards each other (the point of the method)
    gap_munich = sum(
        abs(
            _value(values, "munich_incurred_ultimate", o)
            - _value(values, "munich_paid_ultimate", o)
        )
        for o in origins
    )
    gap_separate = sum(
        abs(
            _value(values, "chain_ladder_incurred_ultimate", o)
            - _value(values, "chain_ladder_paid_ultimate", o)
        )
        for o in origins
    )
    assert gap_munich < gap_separate
    information = _information("MT12-munich-chain-ladder-mcl")
    for kind in ("paid", "incurred"):
        _close(values, "lambda_without_last_link", kind, _value(values, "lambda", kind), 1e-8)
        # the variant with every link is information only (decision 0607)
        assert ("lambda_all_links", kind) not in values
        assert information[("lambda_all_links", kind)] != pytest.approx(
            _value(values, "lambda", kind), rel=1e-2
        )


# ------------------------------------------------------------------ MT13


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_mt13_package_blends_equal_the_spec_formulas(name: str) -> None:
    folder, values = _ref(f"MT13-benktander-{name}")
    tri = _array(folder / "triangle.csv")
    manifest = load_reference(f"MT13-benktander-{name}")["manifest"]
    prior = manifest["prior"]["earned_premium_each_origin"] * manifest["prior"]["prior_loss_ratio"]
    origins = load_triangle(folder / "triangle.csv")["origins"]
    latest, cdf = _latest(tri), _cdf_by_origin(tri)
    p = 1 / cdf
    q = 1 - p
    bf = latest + q * prior
    gb1 = latest + q * bf
    gb2 = latest + q * gb1
    for i, origin in enumerate(origins):
        _close(values, "chain_ladder_ultimate", origin, float(latest[i] * cdf[i]))
        _close(values, "bornhuetter_ferguson_ultimate", origin, float(bf[i]))
        _close(values, "benktander_k1_ultimate", origin, float(gb1[i]))
        _close(values, "benktander_k2_ultimate", origin, float(gb2[i]))


def test_mt13_hand_fixture_from_triangles() -> None:
    folder, values = _ref("MT13-benktander-4x4")
    prior_lr = Fr(3, 5)
    premium = {
        int(r["origin"]): int(r["earned_premium"]) for r in load_table(folder / "premium.csv")
    }
    for basis in ("paid", "incurred"):
        path = folder / f"{basis}_triangle.csv"
        rows = _array(path)
        origins = load_triangle(path)["origins"]
        factors = [
            Fr(int(np.nansum(rows[: 3 - j, j + 1])), int(np.nansum(rows[: 3 - j, j])))
            for j in range(3)
        ]
        for i, origin in enumerate(origins):
            last = 3 - i
            cdf = math.prod(factors[last:], start=Fr(1))
            latest = Fr(int(rows[i][last]))
            q = 1 - 1 / cdf
            bf = latest + q * prior_lr * premium[origin]
            gb1 = latest + q * bf
            assert float(gb1) == pytest.approx(
                _value(values, f"{basis}_benktander_k1_ultimate", origin), rel=1e-12
            )
            assert float(bf) == pytest.approx(
                _value(values, f"{basis}_bornhuetter_ferguson_ultimate", origin), rel=1e-12
            )
            assert float((1 - q) * latest * cdf + q * bf) == pytest.approx(float(gb1), rel=1e-12)


# ------------------------------------------------------------------ MT14


@pytest.mark.parametrize("name", ["raa", "genins"])
@pytest.mark.parametrize("curve", ["exponential", "inverse_power"])
def test_mt14_tail_fit_and_tail_from_the_triangle(name: str, curve: str) -> None:
    folder, values = _ref(f"MT14-tail-curves-{name}")
    tri = _array(folder / "triangle.csv")
    f = _volume_factors(tri)
    used = [j for j, v in enumerate(f) if v > 1.00001]
    x = np.array([j + 1 for j in used], dtype=float)
    y = np.log(f[used] - 1)
    design = x if curve == "exponential" else np.log(x)
    slope, intercept = np.polyfit(design, y, 1)
    b = slope if curve == "exponential" else -slope
    _close(values, f"{curve}_fit", "a", float(intercept), 1e-8)
    _close(values, f"{curve}_fit", "b", float(b), 1e-8)

    def excess(t: int) -> float:
        return (
            math.exp(intercept + slope * t)
            if curve == "exponential"
            else math.exp(intercept) * t**slope
        )

    first = len(f) + 1
    package = math.prod(1 + excess(first + k) for k in range(100))
    _close(values, f"{curve}_tail", "package_100_periods", package, 1e-8)
    spec, t = 1.0, first
    while t - first < 100 and excess(t) >= 1e-4:
        spec *= 1 + excess(t)
        t += 1
    # the old stopping rule is information only (decision 0608)
    assert (f"{curve}_tail", "spec_stop_below_1e-4") not in values
    dropped = _information(f"MT14-tail-curves-{name}")[(f"{curve}_tail", "stop_below_1e-4")]
    assert spec == pytest.approx(dropped, rel=1e-8)
    assert spec <= package
    if curve == "inverse_power":
        # the fixed 100 periods leave out the rest of the product (information, decision 0614)
        t_all = np.arange(first, first + 1_000_000, dtype=float)
        inc = math.exp(intercept) * t_all**slope
        infinite = math.exp(float(np.sum(np.log1p(inc[inc >= 1e-12]))))
        info = _information(f"MT14-tail-curves-{name}")[(f"{curve}_tail", "infinite_product")]
        assert infinite == pytest.approx(info, rel=1e-6)
        assert infinite > package
    if curve == "exponential":
        assert b < 0
    else:
        assert b > 1, "the inverse power product would not converge otherwise (spec MT14)"


# ------------------------------------------------------------------ MT15


def test_mt15_separation_recursion_from_the_triangle() -> None:
    folder, values = _ref("MT15-separation-4x4")
    x = _array(folder / "incremental_paid.csv")
    counts = [int(r["ultimate_claim_count"]) for r in load_table(folder / "claim_counts.csv")]
    size = 4
    s = [[Fr(int(x[i][j])) / counts[i] for j in range(size - i)] for i in range(size)]
    d = [sum((s[i][k - i] for i in range(k + 1)), Fr(0)) for k in range(size)]
    v = [sum((s[i][j] for i in range(size - j)), Fr(0)) for j in range(size)]
    lam = [Fr(0)] * size
    r = [Fr(0)] * size
    lam[size - 1] = d[size - 1]
    for j in range(size - 1, -1, -1):
        r[j] = v[j] / sum(lam[j:], Fr(0))
        if j:
            lam[j - 1] = d[j - 1] / (1 - sum(r[j:], Fr(0)))
    for j in range(size):
        assert float(lam[j]) == pytest.approx(
            _value(values, "calendar_index_lambda", f"k{j}"), rel=1e-12
        )
        assert float(r[j]) == pytest.approx(
            _value(values, "development_pattern_r", f"dev{j}"), rel=1e-12
        )
    assert sum(r) == 1
    # projection with the index growing 5 % a period
    total = Fr(0)
    for i in range(size):
        future = Fr(0)
        for j in range(size - i, size):
            future += counts[i] * r[j] * lam[size - 1] * Fr(21, 20) ** (i + j - (size - 1))
        total += future
        assert float(future) == pytest.approx(
            _value(values, "reserve_assumed_5pct", 2021 + i), rel=1e-12
        )
    assert float(total) == pytest.approx(
        _value(values, "total_reserve_assumed_5pct", "all"), rel=1e-12
    )


def test_mt15_ols_trend_matches_a_spreadsheet_slope() -> None:
    _, values = _ref("MT15-separation-4x4")
    lam = [_value(values, "calendar_index_lambda", f"k{k}") for k in range(4)]
    slope = float(np.polyfit(np.arange(4), np.log(lam), 1)[0])
    _close(values, "future_index_trend", "slope_of_ln_lambda", slope)
    _close(values, "future_index_trend", "growth_g", math.exp(slope) - 1)


# ------------------------------------------------------------------ MT16


def test_mt16_frequency_severity_from_the_triangles() -> None:
    folder, values = _ref("MT16-frequency-severity-4x4")
    counts = _array(folder / "reported_counts.csv")
    incurred = _array(folder / "incurred.csv")
    origins = load_triangle(folder / "incurred.csv")["origins"]
    exposure = [int(r["earned_exposure"]) for r in load_table(folder / "exposure.csv")]

    def ultimates(rows: np.ndarray) -> tuple[list[Fr], list[Fr]]:
        factors = [
            Fr(int(np.nansum(rows[: 3 - j, j + 1])), int(np.nansum(rows[: 3 - j, j])))
            for j in range(3)
        ]
        cdfs = [math.prod(factors[3 - i :], start=Fr(1)) for i in range(4)]
        return [Fr(int(rows[i][3 - i])) * cdfs[i] for i in range(4)], cdfs

    n_ult, _ = ultimates(counts)
    u_ult, cdf_inc = ultimates(incurred)
    t = np.arange(4, dtype=float)
    sev = [float(u / n) for u, n in zip(u_ult, n_ult, strict=True)]
    mature = [i for i in range(4) if 1 / float(cdf_inc[i]) >= 0.9]
    assert mature == [0, 1, 2]
    slope, intercept = np.polyfit(t[mature], np.log([sev[i] for i in mature]), 1)
    for i, origin in enumerate(origins):
        _close(values, "frequency", origin, float(n_ult[i]) / exposure[i], 1e-12)
        projected = math.exp(intercept + slope * t[i])
        _close(values, "frequency_severity_ultimate", origin, float(n_ult[i]) * projected, 1e-9)
    freq = [float(n_ult[i]) / exposure[i] for i in range(4)]
    f_slope = float(np.polyfit(t, np.log(freq), 1)[0])
    _close(values, "frequency_trend", "slope", f_slope, 1e-9)


# ------------------------------------------------------------------ MT17, MT18 (scipy refits)


def _samples(path: Path) -> dict[str, np.ndarray]:
    rows = load_table(path)
    return {name: np.array([float(r[name]) for r in rows]) for name in rows[0] if name != "claim"}


def test_mt17_lognormal_fit_equals_closed_form() -> None:
    folder, values = _ref("MT17-severity-fits")
    x = _samples(folder / "samples.csv")["lognormal"]
    mu, sigma = float(np.mean(np.log(x))), float(np.std(np.log(x)))
    _close(values, "closed_form_lognormal", "mu", mu, 1e-12)
    _close(values, "closed_form_lognormal", "sigma", sigma, 1e-12)
    _close(values, "mle_sigma", "lognormal_sample/lognormal", sigma, 1e-4)
    assert math.log(_value(values, "mle_exp_mu", "lognormal_sample/lognormal")) == pytest.approx(
        mu, rel=1e-4
    )
    _close(
        values,
        "sample_mean_gamma",
        "mean",
        float(np.mean(_samples(folder / "samples.csv")["gamma"])),
        1e-12,
    )


@pytest.mark.parametrize(
    ("family", "dist"),
    [("gamma", stats.gamma), ("weibull", stats.weibull_min), ("pareto", stats.lomax)],
)
def test_mt17_refit_reproduces_frozen_estimates(family: str, dist) -> None:
    folder, values = _ref("MT17-severity-fits")
    x = _samples(folder / "samples.csv")[family]
    first, second = {
        "gamma": ("shape", "scale"),
        "weibull": ("shape", "scale"),
        "pareto": ("alpha", "theta"),
    }[family]
    shape, _, scale = dist.fit(x, floc=0)
    key = f"{family}_sample/{family}"
    _close(values, f"mle_{first}", key, float(shape), 1e-4)
    _close(values, f"mle_{second}", key, float(scale), 1e-4)
    ll = float(np.sum(dist.logpdf(x, shape, 0, scale)))
    _close(values, "loglik", key, ll, 1e-4)
    # the true family wins the AIC on its own sample, as frozen
    index = ["lognormal", "gamma", "weibull", "pareto"].index(family)
    assert _value(values, "lowest_aic_family", f"{family}_sample") == index


def test_mt18_gpd_refit_and_closed_forms() -> None:
    folder, values = _ref("MT18-gpd-fits")
    sample = _samples(folder / "sample_lognormal.csv")["size"]
    u = float(np.quantile(sample, 0.90))
    _close(values, "lognormal_sample", "threshold_u", u, 1e-12)
    xi, _, sigma = stats.genpareto.fit(sample[sample > u] - u, floc=0)
    _close(values, "lognormal_sample", "xi", float(xi), 1e-4)
    _close(values, "lognormal_sample", "sigma", float(sigma), 1e-4)
    excess = _samples(folder / "sample_gpd_excesses.csv")["excess_over_100000"]
    xi2, _, sigma2 = stats.genpareto.fit(excess, floc=0)
    _close(values, "gpd_sample", "xi", float(xi2), 1e-4)
    _close(values, "gpd_sample", "sigma", float(sigma2), 1e-4)


def test_mt18_closed_forms_against_scipy_distribution() -> None:
    _, values = _ref("MT18-gpd-closed-forms")
    u, sigma, xi, n, n_u = 100.0, 50.0, 0.25, 2000, 100
    dist = stats.genpareto(c=xi, loc=u, scale=sigma)
    for p in (0.99, 0.995):
        # P(X > x_p) = N_u / n x P(excess > x_p - u) = 1 - p
        x_p = float(dist.ppf(1 - (1 - p) * n / n_u))
        _close(values, "quantile_xi_0.25", f"p{p}", x_p, 1e-9)
        # expected shortfall of a generalised Pareto above x_p, from scipy's own mean excess
        es = x_p + (sigma + xi * (x_p - u)) / (1 - xi)
        _close(values, "expected_shortfall_xi_0.25", f"p{p}", es, 1e-9)
    z_50 = float(dist.ppf(1 - 1 / (n_u / 10 * 50)))
    _close(values, "return_level_xi_0.25", "T50", z_50, 1e-9)


# ------------------------------------------------------------------ MT19


def test_mt19_kaplan_meier_from_the_times() -> None:
    folder, values = _ref("MT19-kaplan-meier-ten-times")
    rows = [(int(r["time"]), int(r["event"])) for r in load_table(folder / "times.csv")]
    assert len(rows) == 10
    surv, green = Fr(1), Fr(0)
    z = stats.norm.ppf(0.975)
    for t in sorted({t for t, e in rows if e}):
        at_risk = sum(1 for tt, _ in rows if tt >= t)
        events = sum(1 for tt, e in rows if tt == t and e)
        surv *= Fr(at_risk - events, at_risk)
        green += Fr(events, at_risk * (at_risk - events))
        assert float(surv) == pytest.approx(_value(values, "survival", t), rel=1e-12)
        se = float(surv) * math.sqrt(float(green))
        assert se == pytest.approx(_value(values, "greenwood_standard_error", t), rel=1e-12)
        theta = z * math.sqrt(float(green)) / abs(math.log(float(surv)))
        assert float(surv) ** math.exp(theta) == pytest.approx(
            _value(values, "log_log_lower_95", t), rel=1e-9
        )
    assert _value(values, "median", "time") == 7


def _cox_design(folder: Path, covariates: list[str]):
    rows = load_table(folder / "data.csv")
    time = np.array([float(r["time"]) for r in rows])
    event = np.array([int(r["event"]) for r in rows])
    x = np.array([[float(r[c]) for c in covariates] for r in rows])
    return time, event, x


def _cox_fit(time, event, x, ties: str) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Cox partial likelihood by Newton steps on finite differences (numpy and scipy only)."""
    times = np.unique(time[event == 1])
    at_risk = (time[None, :] >= times[:, None]).astype(float)
    died = ((time[None, :] == times[:, None]) & (event[None, :] == 1)).astype(float)
    d = died.sum(axis=1)
    steps = np.arange(int(d.max()))[:, None]

    def loglik(beta: np.ndarray) -> float:
        eta = x @ beta
        w = np.exp(eta)
        risk, tot, s = at_risk @ w, died @ w, died @ eta
        if ties == "breslow":
            return float(np.sum(s - d * np.log(risk)))
        frac = steps / d[None, :]
        with np.errstate(invalid="ignore"):
            inner = np.where(steps < d[None, :], np.log(risk[None, :] - frac * tot[None, :]), 0.0)
        return float(np.sum(s) - np.sum(inner))

    p = x.shape[1]
    beta = optimize.minimize(
        lambda b: -loglik(b), np.zeros(p), method="BFGS", options={"gtol": 1e-9}
    ).x

    def derivatives(b: np.ndarray, h: float = 1e-4) -> tuple[np.ndarray, np.ndarray]:
        grad = np.zeros(p)
        hess = np.zeros((p, p))
        f0 = loglik(b)
        for i in range(p):
            ei = np.eye(p)[i] * h
            grad[i] = (loglik(b + ei) - loglik(b - ei)) / (2 * h)
            hess[i, i] = (loglik(b + ei) - 2 * f0 + loglik(b - ei)) / h**2
            for j in range(i):
                ej = np.eye(p)[j] * h
                hess[i, j] = hess[j, i] = (
                    loglik(b + ei + ej)
                    - loglik(b + ei - ej)
                    - loglik(b - ei + ej)
                    + loglik(b - ei - ej)
                ) / (4 * h**2)
        return grad, hess

    for _ in range(4):
        grad, hess = derivatives(beta)
        beta = beta - np.linalg.solve(hess, grad)
    _, hess = derivatives(beta)
    se = np.sqrt(np.diag(np.linalg.inv(-hess)))
    return beta, se, loglik(np.zeros(p)), loglik(beta)


@pytest.mark.parametrize(
    ("name", "covariates"),
    [("ovarian", ["age", "resid.ds", "rx", "ecog.ps"]), ("lung", ["age", "sex", "ph.ecog"])],
)
@pytest.mark.parametrize("ties", ["efron", "breslow"])
def test_mt19_cox_reference_is_reproduced_with_scipy(
    name: str, covariates: list[str], ties: str
) -> None:
    folder, values = _ref(f"MT19-cox-{name}")
    time, event, x = _cox_design(folder, covariates)
    assert _value(values, "data", "n") == len(time)
    assert _value(values, "data", "events") == event.sum()
    beta, se, null, fit = _cox_fit(time, event, x, ties)
    for i, covariate in enumerate(covariates):
        assert beta[i] == pytest.approx(_value(values, f"{ties}_coef", covariate), rel=1e-5)
        assert se[i] == pytest.approx(_value(values, f"{ties}_se", covariate), rel=1e-5)
    assert fit == pytest.approx(_value(values, f"{ties}_loglik", "fit"), rel=1e-6)
    assert null == pytest.approx(_value(values, f"{ties}_loglik", "null"), rel=1e-6)
    assert 2 * (fit - null) == pytest.approx(
        _value(values, f"{ties}_lr_test", "statistic"), rel=1e-5
    )


def test_mt19_efron_and_breslow_differ_only_with_ties() -> None:
    for name, expect_equal in (("ovarian", True), ("lung", False)):
        _, values = _ref(f"MT19-cox-{name}")
        efron = reference_series(values, "efron_coef")
        breslow = reference_series(values, "breslow_coef")
        same = all(efron[k] == pytest.approx(breslow[k], rel=1e-9) for k in efron)
        assert same is expect_equal
        assert (_value(values, "data", "tied_event_times") == 0) is expect_equal


# ------------------------------------------------------------------ MT20


def test_mt20_credibility_from_the_cells() -> None:
    folder, values = _ref("MT20-credibility-actual-over-expected")
    n_full = (stats.norm.ppf(0.95) / 0.05) ** 2
    _close(values, "limited_fluctuation", "full_credibility_deaths_nF", float(n_full), 1e-12)
    tot_a = tot_e = 0.0
    for row in load_table(folder / "cells.csv"):
        exposure, rate, actual = (
            float(row["central_exposure_life_years"]),
            float(row["reference_rate"]),
            int(row["actual_deaths"]),
        )
        expected = exposure * rate
        tot_a, tot_e = tot_a + actual, tot_e + expected
        cell = row["cell"]
        _close(values, "expected_deaths", cell, expected, 1e-12)
        _close(values, "actual_over_expected", cell, actual / expected, 1e-12)
        _close(
            values,
            "garwood_lower",
            cell,
            float(stats.chi2.ppf(0.025, 2 * actual)) / (2 * expected),
            1e-9,
        )
        _close(
            values,
            "garwood_upper",
            cell,
            float(stats.chi2.ppf(0.975, 2 * actual + 2)) / (2 * expected),
            1e-9,
        )
        z = min(1.0, math.sqrt(actual / n_full))
        _close(values, "credibility_Z", cell, z, 1e-12)
        _close(values, "credibility_weighted_ae", cell, z * actual / expected + 1 - z, 1e-12)
    _close(values, "total", "actual_over_expected", tot_a / tot_e, 1e-12)


# ------------------------------------------------------------------ MT21


def test_mt21_reinsurance_programme_properties() -> None:
    folder, values = _ref("MT21-reinsurance-twelve-claims")
    claims = load_table(folder / "claims.csv")
    assert len(claims) == 12
    tot = {k: Fr(0) for k in ("qs", "sp", "xl", "psp", "pqs", "pxl", "gross")}
    for row in claims:
        cid, si, gross = int(row["claim_id"]), int(row["sum_insured"]), Fr(int(row["gross_loss"]))
        share = Fr(min(max(si - 400, 0), 4 * 400), si)
        sp = share * gross
        qs = Fr(3, 10) * gross
        xl = Fr(min(200, max(0, int(gross) - 100)))
        after_sp = gross - sp
        pqs = Fr(3, 10) * after_sp
        after_qs = after_sp - pqs
        pxl = Fr(min(200, max(0, after_qs - 100)))
        net = after_qs - pxl
        assert 0 <= sp <= gross and 0 <= qs <= gross and 0 <= xl <= gross
        assert net >= 0 and net == gross - sp - pqs - pxl, "net equals gross minus ceded"
        assert float(sp) == pytest.approx(_value(values, "surplus_ceded", cid), rel=1e-12)
        assert float(qs) == pytest.approx(_value(values, "quota_share_ceded", cid), rel=1e-12)
        assert float(xl) == pytest.approx(_value(values, "excess_of_loss_ceded", cid), rel=1e-12)
        assert float(pxl) == pytest.approx(
            _value(values, "programme_excess_of_loss_ceded", cid), rel=1e-12
        )
        assert float(net) == pytest.approx(_value(values, "programme_net", cid), rel=1e-12)
        for key, amount in (
            ("qs", qs),
            ("sp", sp),
            ("xl", xl),
            ("psp", sp),
            ("pqs", pqs),
            ("pxl", pxl),
            ("gross", gross),
        ):
            tot[key] += amount
    assert float(tot["gross"]) == _value(values, "total", "gross_loss")
    assert float(tot["pqs"]) == pytest.approx(
        _value(values, "total", "programme_quota_share_ceded"), rel=1e-12
    )
    # ceded by the quota share on what the surplus left is smaller than the quota share on gross
    assert tot["pqs"] < tot["qs"]


# ------------------------------------------------------------------ MT22


def test_mt22_errors_bias_mae_rmse() -> None:
    folder, values = _ref("MT22-back-test-four-origins")
    reference = {
        int(r["origin"]): int(r["reference_ultimate"]) for r in load_table(folder / "reference.csv")
    }
    for row in load_table(folder / "estimates.csv"):
        label = f"{row['method']}_h{row['horizon_months']}"
        est = {o: int(row[f"u_{o}"]) for o in reference}
        w = np.array([reference[o] for o in reference], dtype=float)
        e = np.array([(est[o] - reference[o]) / reference[o] for o in reference])
        _close(values, f"bias_{label}", "all", float(np.sum(w * e) / np.sum(w)), 1e-12)
        _close(values, f"mae_{label}", "all", float(np.sum(w * np.abs(e)) / np.sum(w)), 1e-12)
        _close(
            values, f"rmse_{label}", "all", math.sqrt(float(np.sum(w * e**2) / np.sum(w))), 1e-12
        )
