# ruff: noqa: E501
# pyright: reportPrivateImportUsage=false, reportIndexIssue=false, reportArgumentType=false, reportCallIssue=false
"""Freeze the severity-fit and extreme-value references (MT17, MT18) with scipy.stats.

Run once by hand:  uv run python tests/benchmarks/tools/freeze_scipy.py

Samples are drawn with numpy default_rng at a fixed seed and written to CSV, so a test never depends
on a random stream: it reads the sample and compares its own maximum-likelihood fit with the frozen
scipy estimates (location fixed at zero, spec MT17 benchmark, 1e-4 relative).
"""

import numpy as np
import scipy
from freeze_common import TIER_B_DIR, write_manifest, write_table, write_values
from scipy import stats

SCRIPT = "tests/benchmarks/tools/freeze_scipy.py"
SEED = 20261024
N = 500
TOL = 1e-4

FAMILIES = {
    "lognormal": stats.lognorm,
    "gamma": stats.gamma,
    "weibull": stats.weibull_min,
    "pareto": stats.lomax,
}
# names of the (shape, scale) parameters per family, in scipy order without the location
PARAMETER_NAMES = {
    "lognormal": ("sigma", "exp_mu"),
    "gamma": ("shape", "scale"),
    "weibull": ("shape", "scale"),
    "pareto": ("alpha", "theta"),
}


def freeze_severity() -> None:
    folder = TIER_B_DIR / "MT17-severity-fits"
    rng = np.random.default_rng(SEED)
    samples = {
        "lognormal": stats.lognorm.rvs(s=1.2, scale=np.exp(10.0), size=N, random_state=rng),
        "gamma": stats.gamma.rvs(a=2.5, scale=4000.0, size=N, random_state=rng),
        "weibull": stats.weibull_min.rvs(c=1.5, scale=8000.0, size=N, random_state=rng),
        "pareto": stats.lomax.rvs(c=3.0, scale=50000.0, size=N, random_state=rng),
    }
    write_table(
        folder / "samples.csv",
        ["claim", *samples],
        [(k + 1, *[repr(float(samples[n][k])) for n in samples]) for k in range(N)],
    )
    truth = {
        "lognormal": "mu 10, sigma 1.2",
        "gamma": "shape 2.5, scale 4000",
        "weibull": "shape 1.5, scale 8000",
        "pareto": "alpha 3, theta 50000 (Pareto II, Lomax)",
    }
    rows: list[tuple] = []
    x_log = samples["lognormal"]
    rows += [
        ("closed_form_lognormal", "mu", float(np.mean(np.log(x_log))), 1e-12, "mean of ln x"),
        (
            "closed_form_lognormal",
            "sigma",
            float(np.std(np.log(x_log))),
            1e-12,
            "standard deviation of ln x, divisor n",
        ),
        (
            "sample_mean_gamma",
            "mean",
            float(np.mean(samples["gamma"])),
            1e-12,
            "mean of the gamma sample: the scale of an exponential fit (gamma with shape 1 fixed)",
        ),
    ]
    # every family fitted to every sample, so a selection by AIC has a frozen answer too
    for sample_name, x in samples.items():
        aics = {}
        for family, dist in FAMILIES.items():
            params = dist.fit(x, floc=0)
            ll = float(np.sum(dist.logpdf(x, *params)))
            aics[family] = 2 * 2 - 2 * ll
            shape_or_sigma, _, scale = params
            key = f"{sample_name}_sample/{family}"
            first, second = PARAMETER_NAMES[family]
            rows.append((f"mle_{first}", key, float(shape_or_sigma), TOL, "scipy fit, floc=0"))
            rows.append((f"mle_{second}", key, float(scale), TOL, "scipy fit, floc=0"))
            rows.append(("loglik", key, ll, TOL, "sum of logpdf at the fit"))
            rows.append(("aic", key, aics[family], TOL, "2 x 2 - 2 loglik"))
        best = min(aics, key=lambda k: aics[k])
        rows.append(
            (
                "lowest_aic_family",
                f"{sample_name}_sample",
                float(list(aics).index(best)),
                0.0,
                f"index in lognormal, gamma, weibull, pareto = {best}",
            )
        )
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT17-severity-fits",
            "spec_ids": ["MT17"],
            "kind": "library_reference",
            "title": "Maximum-likelihood fits of lognormal, gamma, Weibull and Pareto II to fixed samples",
            "source": {
                "tool": "scipy.stats",
                "version": scipy.__version__,
                "numpy_version": np.__version__,
                "calls": ["<family>.fit(x, floc=0) for lognorm, gamma, weibull_min, lomax"],
            },
            "how_produced": (
                f"Run {SCRIPT}. Samples drawn with numpy default_rng({SEED}), {N} sizes each, "
                "written to samples.csv."
            ),
            "seed": SEED,
            "samples_drawn_from": truth,
            "files": {"samples": "samples.csv", "values": "values.csv"},
            "tolerance_note": (
                "1e-4 relative (spec MT17 benchmark: an independent optimiser of the same likelihood)."
            ),
            "notes": [
                "Parameter names: lognormal sigma is scipy's s and exp_mu is its scale = exp(mu); "
                "Pareto is the two-parameter Pareto II (Lomax) with alpha and theta.",
                "The closed-form lognormal rows (mean and divisor-n standard deviation of the logs) "
                "equal the fit: mu = ln(exp_mu), sigma = sigma.",
            ],
        },
    )


def freeze_gpd() -> None:
    folder = TIER_B_DIR / "MT18-gpd-fits"
    rng = np.random.default_rng(SEED + 1)
    body = stats.lognorm.rvs(s=1.3, scale=np.exp(9.5), size=3000, random_state=rng)
    u_body = float(np.quantile(body, 0.90))
    u_true = 100_000.0
    excess_true = stats.genpareto.rvs(c=0.3, scale=20_000.0, size=400, random_state=rng)
    write_table(
        folder / "sample_lognormal.csv",
        ["claim", "size"],
        [(k + 1, repr(float(v))) for k, v in enumerate(body)],
    )
    write_table(
        folder / "sample_gpd_excesses.csv",
        ["claim", "excess_over_100000"],
        [(k + 1, repr(float(v))) for k, v in enumerate(excess_true)],
    )
    above = body[body > u_body] - u_body
    xi, _, sigma = stats.genpareto.fit(above, floc=0)
    rows: list[tuple] = [
        ("lognormal_sample", "threshold_u", u_body, 1e-12, "np.quantile(sample, 0.90), linear"),
        ("lognormal_sample", "exceedances", float(len(above)), 0.0, "sizes above u"),
        ("lognormal_sample", "xi", float(xi), TOL, "scipy genpareto.fit(excess, floc=0), shape c"),
        ("lognormal_sample", "sigma", float(sigma), TOL, "scipy scale"),
        (
            "lognormal_sample",
            "loglik",
            float(np.sum(stats.genpareto.logpdf(above, xi, 0, sigma))),
            TOL,
            "at the fit",
        ),
    ]
    xi2, _, sigma2 = stats.genpareto.fit(excess_true, floc=0)
    rows += [
        (
            "gpd_sample",
            "threshold_u",
            u_true,
            0.0,
            "stated threshold; the 400 excesses are drawn from xi 0.3, sigma 20000",
        ),
        ("gpd_sample", "xi", float(xi2), TOL, "scipy genpareto.fit(excess, floc=0)"),
        ("gpd_sample", "sigma", float(sigma2), TOL, "scipy scale"),
        (
            "gpd_sample",
            "loglik",
            float(np.sum(stats.genpareto.logpdf(excess_true, xi2, 0, sigma2))),
            TOL,
            "at the fit",
        ),
    ]
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT18-gpd-fits",
            "spec_ids": ["MT18"],
            "kind": "library_reference",
            "title": "Generalised Pareto maximum likelihood above a stated threshold",
            "source": {
                "tool": "scipy.stats",
                "version": scipy.__version__,
                "numpy_version": np.__version__,
                "calls": ["genpareto.fit(excess, floc=0)"],
            },
            "how_produced": f"Run {SCRIPT}. Samples drawn with numpy default_rng({SEED + 1}).",
            "seed": SEED + 1,
            "files": {
                "lognormal_sample": "sample_lognormal.csv",
                "gpd_excesses": "sample_gpd_excesses.csv",
                "values": "values.csv",
            },
            "tolerance_note": "1e-4 relative (spec MT18 benchmark).",
            "notes": [
                "The first sample is lognormal (3000 sizes, threshold at the empirical 90th "
                "percentile); the second is 400 excesses drawn from a generalised Pareto with xi 0.3 "
                "and sigma 20000 above 100000.",
                "The automatic threshold rule (ForwardStop with bootstrap Anderson-Darling p-values) "
                "has no frozen reference here: it rests on random p-values. Its ForwardStop index for "
                "given p-values is a hand case for the P25 tests.",
            ],
        },
    )


if __name__ == "__main__":
    freeze_severity()
    freeze_gpd()
    print("done")
