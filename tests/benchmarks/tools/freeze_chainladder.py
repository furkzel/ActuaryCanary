# ruff: noqa: E501
# pyright: reportPrivateImportUsage=false, reportIndexIssue=false, reportArgumentType=false, reportCallIssue=false
"""Freeze the tier B references that the chainladder package supplies (MT11, MT12, MT13, MT14).

Run once by hand (the package is a development tool, never a test dependency, decision 0007):

    uv run python tests/benchmarks/tools/freeze_chainladder.py

It rewrites the folders tier_b/MT11-*, MT12-*, MT13-*, MT14-*. Every number that the script derives
itself (and not the package) is marked "derived" in the note column of values.csv.
"""

import math

import chainladder as cl
import numpy as np
from freeze_common import TIER_B_DIR, write_manifest, write_table, write_triangle, write_values

PACKAGE = {"tool": "chainladder", "version": cl.__version__}
SCRIPT = "tests/benchmarks/tools/freeze_chainladder.py"
N_SIMS = 10_000
SEED = 42
N_SEEDS_FOR_TOLERANCE = 30
PERCENTILES = (75.0, 95.0, 99.5)


def triangle_rows(tri) -> tuple[list[int], list[int], list[list[float | None]]]:
    frame = tri.to_frame(origin_as_datetime=False)
    origins = [int(getattr(o, "year", o)) for o in frame.index]
    ages = [int(a) for a in frame.columns]
    rows = [[None if math.isnan(v) else float(v) for v in r] for r in frame.to_numpy()]
    return origins, ages, rows


def origin_values(tri_like) -> list[float]:
    return [float(v) for v in tri_like.to_frame(origin_as_datetime=False).to_numpy().ravel()]


def volume_factors(values: np.ndarray) -> np.ndarray:
    n = values.shape[0]
    return np.array(
        [
            np.nansum(values[: n - 1 - j, j + 1]) / np.nansum(values[: n - 1 - j, j])
            for j in range(n - 1)
        ]
    )


# ---------------------------------------------------------------------------- MT12 Munich


def mack_factors(tri: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Volume-weighted factors and Mack standard deviations, last sigma extrapolated as in Mack."""
    n = tri.shape[0]
    f = volume_factors(tri)
    s2 = np.zeros(n - 1)
    for j in range(n - 2):
        k = n - 1 - j
        ratio = tri[:k, j + 1] / tri[:k, j]
        s2[j] = np.sum(tri[:k, j] * (ratio - f[j]) ** 2) / (k - 1)
    s2[n - 2] = min(s2[n - 3] ** 2 / s2[n - 4], min(s2[n - 4], s2[n - 3]))
    return f, np.sqrt(s2)


def munich_lambdas(paid: np.ndarray, incurred: np.ndarray, last_links: int) -> tuple[float, float]:
    """Correlation parameters from the spec formulas (MT12), using the first n - 1 - drop links.

    last_links = 0 uses every link; 1 leaves out the last link, which rests on one origin and on
    extrapolated variance parameters (what the package does).
    """
    n = paid.shape[0]
    f_p, s_p = mack_factors(paid)
    f_i, s_i = mack_factors(incurred)
    ratio = paid / incurred
    q = np.array([np.nansum(paid[: n - j, j]) / np.nansum(incurred[: n - j, j]) for j in range(n)])
    num_p = den_p = num_i = den_i = 0.0
    for j in range(n - 1 - last_links):
        k = n - 1 - j
        m = k + 1
        rho_i = math.sqrt(np.sum(incurred[:m, j] * (ratio[:m, j] - q[j]) ** 2) / (m - 1))
        rho_p = math.sqrt(np.sum(paid[:m, j] * (1 / ratio[:m, j] - 1 / q[j]) ** 2) / (m - 1))
        r_p = (paid[:k, j + 1] / paid[:k, j] - f_p[j]) / s_p[j] * np.sqrt(paid[:k, j])
        q_p = (1 / ratio[:k, j] - 1 / q[j]) / rho_p * np.sqrt(paid[:k, j])
        r_i = (incurred[:k, j + 1] / incurred[:k, j] - f_i[j]) / s_i[j] * np.sqrt(incurred[:k, j])
        q_i = (ratio[:k, j] - q[j]) / rho_i * np.sqrt(incurred[:k, j])
        num_p += float(np.sum(q_p * r_p))
        den_p += float(np.sum(q_p**2))
        num_i += float(np.sum(q_i * r_i))
        den_i += float(np.sum(q_i**2))
    return num_p / den_p, num_i / den_i


def freeze_munich() -> None:
    folder = TIER_B_DIR / "MT12-munich-chain-ladder-mcl"
    sample = cl.load_sample("mcl")
    origins, ages, paid_rows = triangle_rows(sample["paid"])
    _, _, inc_rows = triangle_rows(sample["incurred"])
    write_triangle(folder / "paid.csv", origins, ages, paid_rows)
    write_triangle(folder / "incurred.csv", origins, ages, inc_rows)

    dev = cl.Development(average="volume", sigma_interpolation="mack").fit_transform(sample)
    munich = cl.MunichAdjustment(paid_to_incurred=[("paid", "incurred")])
    adjusted = munich.fit_transform(dev)
    frame = cl.Chainladder().fit(adjusted).ultimate_.to_frame(origin_as_datetime=False)
    sep = cl.Chainladder().fit(dev).ultimate_.to_frame(origin_as_datetime=False)
    rows: list[tuple] = [
        ("lambda", "paid", float(munich.lambda_["paid"]), 1e-6, "lambda^P, package"),
        ("lambda", "incurred", float(munich.lambda_["incurred"]), 1e-6, "lambda^I, package"),
    ]
    paid_arr = np.array([[np.nan if v is None else v for v in r] for r in paid_rows])
    inc_arr = np.array([[np.nan if v is None else v for v in r] for r in inc_rows])
    all_p, all_i = munich_lambdas(paid_arr, inc_arr, last_links=0)
    cut_p, cut_i = munich_lambdas(paid_arr, inc_arr, last_links=1)
    assert math.isclose(cut_p, float(munich.lambda_["paid"]), rel_tol=1e-9)
    assert math.isclose(cut_i, float(munich.lambda_["incurred"]), rel_tol=1e-9)
    rows += [
        (
            "lambda_all_links",
            "paid",
            all_p,
            1e-9,
            "derived by numpy from the spec text: every link with both residuals",
        ),
        ("lambda_all_links", "incurred", all_i, 1e-9, "derived, as above"),
        (
            "lambda_without_last_link",
            "paid",
            cut_p,
            1e-9,
            "derived: the last link (one origin, extrapolated variance parameters) left out; equals the package",
        ),
        ("lambda_without_last_link", "incurred", cut_i, 1e-9, "derived, as above"),
    ]
    for kind in ("paid", "incurred"):
        for origin, value in zip(origins, frame.loc[kind], strict=True):
            rows.append((f"munich_{kind}_ultimate", origin, float(value), 1e-6, "package"))
        for origin, value in zip(origins, sep.loc[kind], strict=True):
            rows.append((f"chain_ladder_{kind}_ultimate", origin, float(value), 1e-6, "package"))
    for origin, p, i in zip(origins, frame.loc["paid"], frame.loc["incurred"], strict=True):
        rows.append(("munich_paid_to_incurred_ratio", origin, float(p / i), 1e-6, "derived"))
    for origin, p, i in zip(origins, sep.loc["paid"], sep.loc["incurred"], strict=True):
        rows.append(("chain_ladder_paid_to_incurred_ratio", origin, float(p / i), 1e-6, "derived"))
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT12-munich-chain-ladder-mcl",
            "spec_ids": ["MT12"],
            "kind": "library_reference",
            "title": "Munich chain ladder on the Quarg-Mack sample triangles",
            "source": {
                **PACKAGE,
                "data": "chainladder.load_sample('mcl'), columns paid and incurred",
                "calls": [
                    "sample = chainladder.load_sample('mcl')",
                    "dev = chainladder.Development(average='volume', sigma_interpolation='mack')"
                    ".fit_transform(sample)",
                    "mcl = chainladder.MunichAdjustment(paid_to_incurred=[('paid', 'incurred')])",
                    "ultimate = chainladder.Chainladder().fit(mcl.fit_transform(dev)).ultimate_",
                ],
            },
            "how_produced": f"Run {SCRIPT}; values.csv holds the package output unchanged.",
            "files": {"paid": "paid.csv", "incurred": "incurred.csv", "values": "values.csv"},
            "tolerance_note": "1e-6 relative (spec MT12 benchmark).",
            "notes": [
                "Seven accident years, seven ages (12 to 84 months); tail factor 1.0.",
                "The package leaves the last link (one origin, extrapolated variance parameters) out of "
                "the lambda regressions; the spec text says every link with both residuals. The lambdas "
                "differ (paid 0.6360 against 0.6130, incurred 0.4362 against 0.4208). The ultimates "
                "follow the package. Decision 0274.",
                "Published figures of Quarg and Mack (2004) were not opened: UNVERIFIED.",
            ],
        },
    )


# ---------------------------------------------------------------------------- MT11 ODP


def odp_deterministic(values: np.ndarray) -> dict:
    n = values.shape[0]
    f = volume_factors(values)
    cum_fit = np.full((n, n), np.nan)
    for i in range(n):
        last = n - 1 - i
        cum_fit[i, last] = values[i, last]
        for j in range(last - 1, -1, -1):
            cum_fit[i, j] = cum_fit[i, j + 1] / f[j]
    inc_fit = np.full((n, n), np.nan)
    inc_obs = np.full((n, n), np.nan)
    for i in range(n):
        last = n - 1 - i
        inc_fit[i, : last + 1] = np.diff(np.concatenate([[0.0], cum_fit[i, : last + 1]]))
        inc_obs[i, : last + 1] = np.diff(np.concatenate([[0.0], values[i, : last + 1]]))
    unscaled = (inc_obs - inc_fit) / np.sqrt(inc_fit)
    n_cells = n * (n + 1) // 2
    n_params = 2 * n - 1
    phi = float(np.nansum(unscaled**2) / (n_cells - n_params))
    adjusted = unscaled * math.sqrt(n_cells / (n_cells - n_params))
    return {
        "factors": f,
        "fitted": inc_fit,
        "observed": inc_obs,
        "unscaled": unscaled,
        "adjusted": adjusted,
        "phi": phi,
        "n_cells": n_cells,
        "n_params": n_params,
    }


def simulate_totals(tri, seed: int, phi: float) -> tuple[np.ndarray, np.ndarray]:
    """Total reserve per simulation: parameter error only (package) and with gamma process error."""
    sims = cl.BootstrapODPSample(n_sims=N_SIMS, hat_adj=False, random_state=seed).fit_transform(tri)
    model = cl.Chainladder().fit(sims)
    param_only = np.asarray(model.ibnr_.sum("origin").values).reshape(N_SIMS)
    n = tri.shape[-1]
    full = np.asarray(model.full_triangle_.values)[:, 0, :, :n]
    cum_prev = np.concatenate([np.zeros((N_SIMS, n, 1)), full[:, :, :-1]], axis=2)
    future = np.isnan(np.asarray(tri.values)[0, 0])
    means = (full - cum_prev)[:, future]
    assert np.allclose(means.sum(axis=1), param_only, rtol=1e-8)
    rng = np.random.default_rng(seed)
    draws = rng.gamma(np.abs(means) / phi, phi) * np.sign(means)
    return param_only, draws.sum(axis=1)


def summary(x: np.ndarray) -> dict[str, float]:
    out = {"mean": float(np.mean(x)), "sd": float(np.std(x, ddof=1))}
    for q in PERCENTILES:
        out[f"p{q:g}"] = float(np.percentile(x, q))
    return out


def freeze_odp(name: str) -> None:
    folder = TIER_B_DIR / f"MT11-odp-bootstrap-{name}"
    tri = cl.load_sample(name)
    origins, ages, rows = triangle_rows(tri)
    write_triangle(folder / "triangle.csv", origins, ages, rows)
    values = np.array([[np.nan if v is None else v for v in r] for r in rows])
    det = odp_deterministic(values)

    boot = cl.BootstrapODPSample(n_sims=10, hat_adj=False, random_state=1).fit(tri)
    package_phi = float(boot.scale_)
    assert math.isclose(package_phi, det["phi"], rel_tol=1e-9), (package_phi, det["phi"])

    resid_rows = []
    for i, origin in enumerate(origins):
        for j, age in enumerate(ages):
            if not np.isnan(det["observed"][i, j]):
                resid_rows.append(
                    (
                        origin,
                        age,
                        repr(float(det["observed"][i, j])),
                        repr(float(det["fitted"][i, j])),
                        repr(float(det["unscaled"][i, j])),
                        repr(float(det["adjusted"][i, j])),
                    )
                )
    write_table(
        folder / "residuals.csv",
        [
            "origin",
            "age",
            "incremental_paid",
            "fitted_incremental",
            "unscaled_residual",
            "adjusted_residual",
        ],
        resid_rows,
    )

    dev = cl.Development(average="volume").fit_transform(tri)
    chain_ladder_reserve = float(np.nansum(origin_values(cl.Chainladder().fit(dev).ibnr_)))

    param_only, with_process = simulate_totals(tri, SEED, det["phi"])
    stats = {
        "parameter_error_only": summary(param_only),
        "with_process_error": summary(with_process),
    }
    analytic_sd = math.sqrt(
        float(np.var(param_only, ddof=1)) + det["phi"] * float(np.mean(param_only))
    )

    repeats: dict[str, dict[str, list[float]]] = {k: {s: [] for s in stats[k]} for k in stats}
    for seed in range(1000, 1000 + N_SEEDS_FOR_TOLERANCE):
        a, b = simulate_totals(tri, seed, det["phi"])
        for key, sample in (("parameter_error_only", a), ("with_process_error", b)):
            for stat, value in summary(sample).items():
                repeats[key][stat].append(value)

    out: list[tuple] = [
        ("deterministic", "chain_ladder_reserve", chain_ladder_reserve, 1e-9, "package"),
        ("deterministic", "n_cells", float(det["n_cells"]), 0.0, "derived"),
        ("deterministic", "n_parameters", float(det["n_params"]), 0.0, "derived: I + J - 1"),
        (
            "deterministic",
            "scale_parameter_phi",
            det["phi"],
            1e-9,
            "derived by numpy from the spec formulas; equals the package scale_ (checked)",
        ),
    ]
    for j, f in enumerate(det["factors"]):
        out.append(
            ("deterministic", f"volume_factor_{ages[j]}_{ages[j + 1]}", float(f), 1e-9, "derived")
        )
    out.append(
        (
            "deterministic",
            "adjusted_residual_sum_of_squares",
            float(np.nansum(det["adjusted"] ** 2)),
            1e-9,
            "derived",
        )
    )
    labels = {
        "parameter_error_only": "package parameter draws",
        "with_process_error": "derived: package parameter draws plus numpy gamma process error",
    }
    for kind, label in labels.items():
        for stat, value in stats[kind].items():
            spread = float(np.std(repeats[kind][stat], ddof=1)) / abs(value)
            tol = float(f"{3 * spread:.2g}")
            note = (
                f"{label}; seed {SEED}, {N_SIMS} sims; rel_tol = 3 x relative sd of the statistic "
                f"over {N_SEEDS_FOR_TOLERANCE} other seeds ({spread:.2g})"
            )
            if spread > 0.1:
                note += (
                    "; heavy tailed: rare simulations (roughly one in 100,000) have cell means of both signs "
                    "that cancel in the total but not in the process error (sign restored, spec "
                    "MT11), so compare percentiles rather than this value"
                )
            out.append((f"simulation_{kind}_total_reserve", stat, value, tol, note))
    out.append(
        (
            "simulation_with_process_error_total_reserve",
            "sd_analytic",
            analytic_sd,
            0.0,
            "derived: sqrt(var of the parameter-only reserve + phi x its mean); compare with sd "
            "within the Monte Carlo tolerance of sd",
        )
    )
    write_values(folder, out)
    write_manifest(
        folder,
        {
            "id": f"MT11-odp-bootstrap-{name}",
            "spec_ids": ["MT11"],
            "kind": "library_reference",
            "title": f"Over-dispersed Poisson bootstrap on {name}",
            "source": {
                **PACKAGE,
                "data": f"chainladder.load_sample('{name}')",
                "calls": [
                    f"tri = chainladder.load_sample('{name}')",
                    f"boot = chainladder.BootstrapODPSample(n_sims={N_SIMS}, hat_adj=False, "
                    f"random_state={SEED})",
                    "model = chainladder.Chainladder().fit(boot.fit_transform(tri))",
                ],
            },
            "how_produced": (
                f"Run {SCRIPT}. Deterministic rows are computed with numpy from the spec formulas and "
                "agree with the package scale_ to 1e-9. Simulation rows: the package gives the "
                "parameter-error-only totals; process error (gamma, mean m, variance phi m, sign "
                "kept) is added by the script with numpy default_rng(seed)."
            ),
            "seed": SEED,
            "n_simulations": N_SIMS,
            "files": {
                "triangle": "triangle.csv",
                "residuals": "residuals.csv",
                "values": "values.csv",
            },
            "tolerance_note": (
                "Deterministic rows 1e-9 relative. Simulation rows carry their Monte Carlo tolerance "
                "in rel_tol: three times the relative standard deviation of the statistic over "
                f"{N_SEEDS_FOR_TOLERANCE} other seeds of the same size. A test of a different sampler "
                "compares against it as a bound, two independent samplers differ by about 1.5 times "
                "that."
            ),
            "notes": [
                "The package samples parameter error only, uses hat_adj=False (the degrees-of-freedom "
                "adjustment sqrt(n/(n-p)) of the spec) and centres the pool of residuals; the spec "
                "does not centre. Its residual pool differs slightly from residuals.csv.",
                "Published scale parameter of GenIns (England and Verrall) not opened: UNVERIFIED.",
            ],
        },
    )


# ---------------------------------------------------------------------------- MT13 Benktander

BENKTANDER_SETUP = {"raa": (30_000.0, 0.8), "genins": (6_000_000.0, 0.75)}


def freeze_benktander(name: str) -> None:
    folder = TIER_B_DIR / f"MT13-benktander-{name}"
    tri = cl.load_sample(name)
    premium_value, apriori = BENKTANDER_SETUP[name]
    origins, ages, rows = triangle_rows(tri)
    n = len(origins)
    write_triangle(folder / "triangle.csv", origins, ages, rows)
    write_table(
        folder / "premium.csv",
        ["origin", "earned_premium"],
        [(o, repr(premium_value)) for o in origins],
    )
    dev = cl.Development(average="volume").fit_transform(tri)
    premium = tri.latest_diagonal * 0 + premium_value
    latest = np.array(origin_values(tri.latest_diagonal))
    cdf = [float(v) for v in cl.Chainladder().fit(dev).cdf_.to_frame().iloc[0].to_numpy()]
    cdf_by_origin = np.array([cdf[n - 1 - i] for i in range(n)])  # origin i is at age index n-1-i
    p = 1.0 / cdf_by_origin
    q = 1.0 - p
    prior = apriori * premium_value
    cl_ult = latest * cdf_by_origin
    bf_ult = latest + q * prior
    gb1 = latest + q * bf_ult
    gb2 = latest + q * gb1
    z = p / (p + np.sqrt(p))
    mack = z * cl_ult + (1 - z) * bf_ult

    def ult(estimator) -> list[float]:
        return origin_values(estimator.fit(dev, sample_weight=premium).ultimate_)

    pkg = {
        "chain_ladder": origin_values(cl.Chainladder().fit(dev).ultimate_),
        "bornhuetter_ferguson": ult(cl.BornhuetterFerguson(apriori=apriori)),
        "benktander_k1": ult(cl.Benktander(apriori=apriori, n_iters=2)),  # spec k = n_iters - 1
        "benktander_k2": ult(cl.Benktander(apriori=apriori, n_iters=3)),
    }
    checks = {
        "chain_ladder": cl_ult,
        "bornhuetter_ferguson": bf_ult,
        "benktander_k1": gb1,
        "benktander_k2": gb2,
    }
    for key, derived in checks.items():
        assert np.allclose(pkg[key], derived, rtol=1e-9), key
    out: list[tuple] = []
    for key, vals in pkg.items():
        for origin, v in zip(origins, vals, strict=True):
            out.append(
                (
                    f"{key}_ultimate",
                    origin,
                    float(v),
                    1e-9,
                    "package; equals the spec formula (checked)",
                )
            )
    for origin, v in zip(origins, p, strict=True):
        out.append(
            ("reported_share_p", origin, float(v), 1e-9, "derived: 1 / cdf at the latest age")
        )
    for origin, v in zip(origins, z, strict=True):
        out.append(
            ("mack_credibility_weight_Z", origin, float(v), 1e-9, "derived: p / (p + sqrt p)")
        )
    for origin, v in zip(origins, mack, strict=True):
        out.append(
            (
                "mack_credibility_ultimate",
                origin,
                float(v),
                1e-9,
                "derived: Z x chain ladder + (1 - Z) x Bornhuetter-Ferguson",
            )
        )
    write_values(folder, out)
    write_manifest(
        folder,
        {
            "id": f"MT13-benktander-{name}",
            "spec_ids": ["MT13"],
            "kind": "library_reference",
            "title": f"Benktander and Mack credibility blend on {name} with a constant prior",
            "source": {
                **PACKAGE,
                "data": f"chainladder.load_sample('{name}')",
                "calls": [
                    f"tri = chainladder.load_sample('{name}')",
                    "dev = chainladder.Development(average='volume').fit_transform(tri)",
                    f"premium = tri.latest_diagonal * 0 + {premium_value:g}",
                    f"chainladder.Benktander(apriori={apriori}, n_iters=2)"
                    ".fit(dev, sample_weight=premium)",
                    f"chainladder.BornhuetterFerguson(apriori={apriori})"
                    ".fit(dev, sample_weight=premium)",
                ],
            },
            "how_produced": (
                f"Run {SCRIPT}. Package ultimates (checked against the spec formulas); the Mack "
                "credibility rows are derived by the script."
            ),
            "prior": {"earned_premium_each_origin": premium_value, "prior_loss_ratio": apriori},
            "files": {
                "triangle": "triangle.csv",
                "premium": "premium.csv",
                "values": "values.csv",
            },
            "tolerance_note": "1e-9 relative (spec MT13 benchmark). Tail factor 1.0.",
            "notes": [
                "The package counts n_iters = 1 as Bornhuetter-Ferguson; the spec's k is n_iters - 1 "
                "(k = 1 is the classical Benktander, package n_iters = 2).",
                "The samples carry no premium; premium and prior loss ratio are chosen for the test "
                "and are not market figures.",
            ],
        },
    )


# ---------------------------------------------------------------------------- MT14 tail curves

STOP_BELOW = 1e-4
MAX_YEARS = 100


def curve_excess(a: float, b: float, curve: str, t: int) -> float:
    return math.exp(a + b * t) if curve == "exponential" else math.exp(a) * t**b


def spec_tail(a: float, b: float, curve: str, first_t: int) -> tuple[float, int]:
    """Tail by the spec rule: extend one period at a time until f - 1 < stop_below."""
    tail = 1.0
    steps = 0
    while steps < MAX_YEARS:
        excess = curve_excess(a, b, curve, first_t + steps)
        if excess < STOP_BELOW:
            break
        tail *= 1.0 + excess
        steps += 1
    return tail, steps


def freeze_tail(name: str) -> None:
    folder = TIER_B_DIR / f"MT14-tail-curves-{name}"
    tri = cl.load_sample(name)
    origins, ages, rows = triangle_rows(tri)
    write_triangle(folder / "triangle.csv", origins, ages, rows)
    dev = cl.Development(average="volume").fit_transform(tri)
    ldf = [float(v) for v in dev.ldf_.to_frame().iloc[0].to_numpy()]
    n_links = len(ldf)
    out: list[tuple] = []
    for j, f in enumerate(ldf):
        out.append(
            ("selected_factor", f"{ages[j]}_{ages[j + 1]}", f, 1e-9, "package, volume weighted")
        )
    for curve in ("exponential", "inverse_power"):
        fit = cl.TailCurve(curve=curve, extrap_periods=100).fit(dev)
        slope = float(fit.slope_.to_numpy().ravel()[0])
        intercept = float(fit.intercept_.to_numpy().ravel()[0])
        tail = float(np.asarray(fit.tail_).ravel()[0])
        used = [j for j, f in enumerate(ldf) if f > 1.00001]
        x = np.array([j + 1 for j in used], dtype=float)
        y = np.log(np.array([ldf[j] - 1 for j in used]))
        design = x if curve == "exponential" else np.log(x)
        s_chk, a_chk = np.polyfit(design, y, 1)
        assert math.isclose(s_chk, slope, rel_tol=1e-8) and math.isclose(
            a_chk, intercept, rel_tol=1e-8
        )
        r2 = 1.0 - float(np.sum((y - (a_chk + s_chk * design)) ** 2) / np.sum((y - y.mean()) ** 2))
        spec_value, steps = spec_tail(intercept, slope, curve, first_t=n_links + 1)
        spec_b = slope if curve == "exponential" else -slope
        note_b = (
            "package slope"
            if curve == "exponential"
            else "spec b is minus the package slope (ln(f - 1) = a - b ln t)"
        )
        out += [
            (f"{curve}_fit", "a", intercept, 1e-6, "package intercept"),
            (f"{curve}_fit", "b", spec_b, 1e-6, note_b),
            (f"{curve}_fit", "r_squared_log_scale", r2, 1e-6, "derived by numpy"),
            (
                f"{curve}_fit",
                "n_points",
                float(len(used)),
                0.0,
                "factors above 1.00001 (package threshold)",
            ),
            (
                f"{curve}_tail",
                "package_100_periods",
                tail,
                1e-6,
                "package TailCurve(extrap_periods=100); x = link number 1, 2, ...",
            ),
            (
                f"{curve}_tail",
                "spec_stop_below_1e-4",
                spec_value,
                1e-6,
                f"derived: spec rule from a and b, {steps} periods, stops when f - 1 < 1e-4",
            ),
        ]
        for j in range(n_links):
            fitted = 1.0 + curve_excess(intercept, slope, curve, j + 1)
            out.append(
                (
                    f"{curve}_fitted_factor",
                    f"{ages[j]}_{ages[j + 1]}",
                    fitted,
                    1e-6,
                    "derived from a and b",
                )
            )
    write_values(folder, out)
    write_manifest(
        folder,
        {
            "id": f"MT14-tail-curves-{name}",
            "spec_ids": ["MT14"],
            "kind": "library_reference",
            "title": f"Exponential decay and inverse power tails on {name}",
            "source": {
                **PACKAGE,
                "data": f"chainladder.load_sample('{name}')",
                "calls": [
                    f"tri = chainladder.load_sample('{name}')",
                    "dev = chainladder.Development(average='volume').fit_transform(tri)",
                    "chainladder.TailCurve(curve='exponential', extrap_periods=100).fit(dev)",
                    "chainladder.TailCurve(curve='inverse_power', extrap_periods=100).fit(dev)",
                ],
            },
            "how_produced": f"Run {SCRIPT}; the fit rows are checked against a numpy straight-line fit.",
            "files": {"triangle": "triangle.csv", "values": "values.csv"},
            "tolerance_note": "1e-6 relative (spec MT14 benchmark).",
            "notes": [
                "x is the link number (1 for 12-24 months, annual grain), which is the age at the start "
                "of the link in years (spec MT14, CV04).",
                "The package multiplies 100 extension periods; the spec stops when f - 1 falls below "
                "1e-4. Both tails are frozen; for the inverse power curve they differ (decision 0276).",
            ],
        },
    )


if __name__ == "__main__":
    import sys

    wanted = set(sys.argv[1:]) or {"munich", "raa", "genins"}
    if "munich" in wanted:
        freeze_munich()
    for dataset in ("raa", "genins"):
        if dataset in wanted:
            freeze_odp(dataset)
            freeze_benktander(dataset)
            freeze_tail(dataset)
    print("done")
