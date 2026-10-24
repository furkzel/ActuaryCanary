# ruff: noqa: E501
# pyright: reportPrivateImportUsage=false, reportIndexIssue=false, reportArgumentType=false, reportCallIssue=false
"""Build the hand-worked tier B fixtures (MT13, MT15, MT16, MT18, MT19, MT20, MT21).

Run once by hand:

    uv run python tests/benchmarks/tools/build_hand_fixtures.py

All inputs are small round numbers chosen for easy arithmetic. Results are computed with exact
fractions wherever the arithmetic is rational; the note column of values.csv shows the working so
that a reader can redo each number in a spreadsheet. Square roots, logarithms and quantiles of
distributions are floats and say so.
"""

import math
from fractions import Fraction as Fr

import numpy as np
from freeze_common import (
    HAND_TIER_B_DIR,
    write_manifest,
    write_table,
    write_triangle,
    write_values,
)
from scipy import stats

SCRIPT = "tests/benchmarks/tools/build_hand_fixtures.py"
EXACT = 1e-12


def f(x: Fr | float | int) -> float:
    return float(x)


def num(x: Fr | int | float, digits: int = 6) -> str:
    """Short text of a number for the working column."""
    if isinstance(x, Fr) and x.denominator == 1:
        return str(x.numerator)
    if isinstance(x, int):
        return str(x)
    return f"{float(x):.{digits}g}"


# ------------------------------------------------------------------ MT13 Benktander, 4 x 4


def build_mt13() -> None:
    folder = HAND_TIER_B_DIR / "MT13-benktander-4x4"
    paid = [
        [90, 170, 200, 220],
        [110, 210, 256, None],
        [100, 190, None, None],
        [130, None, None, None],
    ]
    incurred = [
        [200, 250, 275, 286],
        [220, 260, 286, None],
        [180, 210, None, None],
        [190, None, None, None],
    ]
    premium = [400, 440, 480, 520]
    origins = [2021, 2022, 2023, 2024]
    ages = [12, 24, 36, 48]
    write_triangle(folder / "paid_triangle.csv", origins, ages, paid)
    write_triangle(folder / "incurred_triangle.csv", origins, ages, incurred)
    write_table(
        folder / "premium.csv",
        ["origin", "earned_premium"],
        list(zip(origins, premium, strict=True)),
    )
    prior_lr = Fr(3, 5)
    rows: list[tuple] = []
    for basis, tri in (("paid", paid), ("incurred", incurred)):
        n = 4
        factors = []
        for j in range(n - 1):
            rws = [r for r in tri if r[j + 1] is not None]
            factors.append(Fr(sum(r[j + 1] for r in rws), sum(r[j] for r in rws)))
        cdf = []
        for j in range(n):
            c = Fr(1)
            for g in factors[j:]:
                c *= g
            cdf.append(c)
        for i, origin in enumerate(origins):
            last = n - 1 - i
            latest = Fr(tri[i][last])
            p = 1 / cdf[last]
            q = 1 - p
            prior = prior_lr * premium[i]
            cl_ult = latest * cdf[last]
            bf = latest + q * prior
            gb1 = latest + q * bf
            gb2 = latest + q * gb1
            z = float(p) / (float(p) + math.sqrt(float(p)))
            mack = z * float(cl_ult) + (1 - z) * float(bf)
            rows += [
                (
                    f"{basis}_reported_share_p",
                    origin,
                    f(p),
                    EXACT,
                    f"1 / cdf = 1 / {num(cdf[last])}",
                ),
                (
                    f"{basis}_chain_ladder_ultimate",
                    origin,
                    f(cl_ult),
                    EXACT,
                    f"{latest} x {num(cdf[last])}",
                ),
                (
                    f"{basis}_bornhuetter_ferguson_ultimate",
                    origin,
                    f(bf),
                    EXACT,
                    f"{latest} + {num(q)} x {num(prior)}",
                ),
                (
                    f"{basis}_benktander_k1_ultimate",
                    origin,
                    f(gb1),
                    EXACT,
                    f"{latest} + {num(q)} x BF {num(bf)}",
                ),
                (
                    f"{basis}_benktander_k2_ultimate",
                    origin,
                    f(gb2),
                    EXACT,
                    f"{latest} + {num(q)} x GB1 {num(gb1)}",
                ),
                (
                    f"{basis}_benktander_weight_on_chain_ladder_k1",
                    origin,
                    f(1 - q),
                    EXACT,
                    "1 - q (closed form: (1 - q) CL + q BF)",
                ),
                (
                    f"{basis}_mack_weight_Z",
                    origin,
                    z,
                    EXACT,
                    f"p / (p + sqrt p) with p = {num(p)} (float)",
                ),
                (
                    f"{basis}_mack_credibility_ultimate",
                    origin,
                    mack,
                    EXACT,
                    f"{num(z)} x {num(cl_ult)} + (1 - {num(z)}) x {num(bf)} (float)",
                ),
            ]
            # the closed form (1 - q) CL + q BF equals the iterated value
            assert (1 - q) * cl_ult + q * bf == gb1
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT13-benktander-4x4",
            "spec_ids": ["MT13"],
            "kind": "hand_worked",
            "title": "Benktander (k = 1, 2) and Mack credibility blend on the 4 x 4 fixture",
            "source": {
                "tool": "exact fractions in Python",
                "data": "tests/fixtures/hand/*.csv (copied here), prior loss ratio 0.6 as in decision 0007",
            },
            "how_produced": f"Run {SCRIPT}. Extends tests/fixtures/hand/expected.yaml; the iterated and the "
            "closed form agree exactly (checked).",
            "files": {
                "paid": "paid_triangle.csv",
                "incurred": "incurred_triangle.csv",
                "premium": "premium.csv",
                "values": "values.csv",
            },
            "tolerance_note": "1e-12 relative.",
            "notes": [
                "Volume-weighted factors, tail 1.0. Benktander k=1 is U = C + q x BF; k=2 iterates once more.",
                "Mack weight Z = p / (p + sqrt p) uses a square root, so those rows are floats.",
            ],
        },
    )


# ------------------------------------------------------------------ MT15 separation method


def build_mt15() -> None:
    folder = HAND_TIER_B_DIR / "MT15-separation-4x4"
    n_claims = [20, 20, 24, 40]
    r_true = [Fr(1, 2), Fr(3, 10), Fr(3, 20), Fr(1, 20)]
    lam_true = [Fr(100), Fr(110), Fr(125), Fr(140)]
    size = 4
    s_true = [[r_true[j] * lam_true[i + j] for j in range(size - i)] for i in range(size)]
    x = [[n_claims[i] * s_true[i][j] for j in range(size - i)] for i in range(size)]
    assert all(v.denominator == 1 for r in x for v in r)
    write_triangle(
        folder / "incremental_paid.csv",
        [2021, 2022, 2023, 2024],
        [0, 1, 2, 3],
        [[int(v) for v in r] + [None] * (size - len(r)) for r in x],
    )
    write_table(
        folder / "claim_counts.csv",
        ["origin", "ultimate_claim_count"],
        list(zip([2021, 2022, 2023, 2024], n_claims, strict=True)),
    )
    # observed per-claim averages s, diagonal sums d_k, column sums v_j
    s = [[x[i][j] / n_claims[i] for j in range(size - i)] for i in range(size)]
    d = [sum(s[i][k - i] for i in range(k + 1)) for k in range(size)]
    v = [sum(s[i][j] for i in range(size - j)) for j in range(size)]
    # recursion from the latest diagonal
    lam = [Fr(0)] * size
    r = [Fr(0)] * size
    lam[size - 1] = d[size - 1]
    for step in range(size - 1, -1, -1):
        r[step] = v[step] / sum(lam[step:])
        if step > 0:
            lam[step - 1] = d[step - 1] / (1 - sum(r[step:]))
    assert lam == lam_true and r == r_true
    rows: list[tuple] = []
    for i in range(size):
        for j in range(size - i):
            rows.append(
                (
                    "avg_paid_per_claim_s",
                    f"{2021 + i}_dev{j}",
                    f(s[i][j]),
                    EXACT,
                    f"X {num(x[i][j])} / n {n_claims[i]}",
                )
            )
    for k in range(size):
        cells = " + ".join(num(s[i][k - i]) for i in range(k + 1))
        rows.append(("diagonal_sum_d", f"k{k}", f(d[k]), EXACT, cells))
    for j in range(size):
        cells = " + ".join(num(s[i][j]) for i in range(size - j))
        rows.append(("column_sum_v", f"dev{j}", f(v[j]), EXACT, cells))
    for k in range(size - 1, -1, -1):
        note = "d_3" if k == size - 1 else f"d_{k} / (1 - sum of r_j for j > {k})"
        rows.append(("calendar_index_lambda", f"k{k}", f(lam[k]), EXACT, note))
        rows.append(
            (
                "development_pattern_r",
                f"dev{k}",
                f(r[k]),
                EXACT,
                f"v_{k} / sum of lambda_k for k >= {k}",
            )
        )
    rows.append(("development_pattern_r", "sum", f(sum(r)), EXACT, "must be 1"))

    def project(lam_future: list[Fr | float], label: str) -> None:
        lams = [*lam, *lam_future]
        for i in range(size):
            observed = sum(x[i])
            future = Fr(0)
            for j in range(size - i, size):
                cell = n_claims[i] * r[j] * lams[i + j]
                future += cell
                rows.append(
                    (
                        f"projected_increment_{label}",
                        f"{2021 + i}_dev{j}",
                        f(cell),
                        EXACT,
                        f"n {n_claims[i]} x r_{j} {num(r[j])} x lambda_{i + j} {num(lams[i + j])}",
                    )
                )
            rows.append(
                (
                    f"reserve_{label}",
                    2021 + i,
                    f(future),
                    EXACT,
                    "sum of the projected increments of the origin",
                )
            )
            rows.append(
                (
                    f"ultimate_{label}",
                    2021 + i,
                    f(observed + future),
                    EXACT,
                    f"paid to date {num(observed)} + reserve",
                )
            )
        rows.append(
            (
                f"total_reserve_{label}",
                "all",
                f(
                    sum(
                        sum(n_claims[i] * r[j] * lams[i + j] for j in range(size - i, size))
                        for i in range(size)
                    )
                ),
                EXACT,
                "sum over origins",
            )
        )

    pi = Fr(1, 20)
    project([lam[-1] * (1 + pi) ** m for m in (1, 2, 3)], "assumed_5pct")
    # OLS trend on ln(lambda) over the four fitted diagonals: g = exp(slope) - 1 (floats)
    ln_lam = np.log([float(v_) for v_ in lam])
    slope = float(np.polyfit(np.arange(size), ln_lam, 1)[0])
    g = math.exp(slope) - 1
    rows.append(
        (
            "future_index_trend",
            "slope_of_ln_lambda",
            slope,
            1e-9,
            "spreadsheet: SLOPE(LN(lambda), k) over k = 0..3 (float)",
        )
    )
    rows.append(("future_index_trend", "growth_g", g, 1e-9, "EXP(slope) - 1 (float)"))
    project([float(lam[-1]) * (1 + g) ** m for m in (1, 2, 3)], "ols_trend")  # type: ignore[list-item]
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT15-separation-4x4",
            "spec_ids": ["MT15"],
            "kind": "hand_worked",
            "title": "Separation method (Taylor) on a 4 x 4 triangle generated exactly from known parameters",
            "source": {"tool": "exact fractions in Python"},
            "how_produced": (
                f"Run {SCRIPT}. The triangle is generated from n = {n_claims}, r = (0.5, 0.3, 0.15, 0.05), "
                "lambda = (100, 110, 125, 140); the recursion gives them back exactly (checked). "
                "The future index is projected at 5 % a period and by the OLS trend of ln lambda."
            ),
            "files": {
                "incremental_paid": "incremental_paid.csv",
                "claim_counts": "claim_counts.csv",
                "values": "values.csv",
            },
            "spreadsheet_layout": [
                "Sheet 1: incremental_paid (X) next to claim_counts (n); s = X / n.",
                "Sheet 2: d_k = sum of s on the anti-diagonal i + j = k; v_j = sum of s in column j.",
                "Sheet 3: from the latest diagonal: lambda_3 = d_3; r_3 = v_3 / lambda_3; lambda_2 = d_2 / (1 - r_3); "
                "r_2 = v_2 / (lambda_2 + lambda_3); and so on.",
                "Sheet 4: future lambda_k = lambda_3 (1 + g)^(k - 3); increment = n_i r_j lambda_(i+j).",
            ],
            "tolerance_note": "1e-12 relative for the exact rows, 1e-9 for the OLS trend rows.",
            "notes": [
                "The columns of incremental_paid.csv are development periods 0 to 3 (annual).",
                "The fixture is exact (no noise), so it proves the algebra of the recursion, not the fit on real data.",
            ],
        },
    )


# ------------------------------------------------------------------ MT16 frequency x severity


def build_mt16() -> None:
    folder = HAND_TIER_B_DIR / "MT16-frequency-severity-4x4"
    origins = [2021, 2022, 2023, 2024]
    ages = [12, 24, 36, 48]
    counts = [
        [400, 460, 475, 480],
        [430, 500, 518, None],
        [450, 520, None, None],
        [470, None, None, None],
    ]
    incurred = [
        [2000, 2200, 2266, 2290],
        [2250, 2475, 2548, None],
        [2400, 2640, None, None],
        [2600, None, None, None],
    ]
    exposure = [1000, 1050, 1100, 1150]
    write_triangle(folder / "reported_counts.csv", origins, ages, counts)
    write_triangle(folder / "incurred.csv", origins, ages, incurred)
    write_table(
        folder / "exposure.csv",
        ["origin", "earned_exposure"],
        list(zip(origins, exposure, strict=True)),
    )

    def chain(tri: list[list[int | None]]) -> list[Fr]:
        out = []
        for j in range(3):
            rws = [r for r in tri if r[j + 1] is not None]
            out.append(Fr(sum(r[j + 1] for r in rws), sum(r[j] for r in rws)))  # type: ignore[misc]
        return out

    def cdf_at(factors: list[Fr], idx: int) -> Fr:
        c = Fr(1)
        for g in factors[idx:]:
            c *= g
        return c

    cf = chain(counts)
    inf = chain(incurred)
    rows: list[tuple] = []
    for j, g in enumerate(cf):
        rows.append(("count_factor", f"{ages[j]}_{ages[j + 1]}", f(g), EXACT, "volume weighted"))
    for j, g in enumerate(inf):
        rows.append(("incurred_factor", f"{ages[j]}_{ages[j + 1]}", f(g), EXACT, "volume weighted"))
    n_ult, u_ult, p_rep, freq, sev = [], [], [], [], []
    for i in range(4):
        last = 3 - i
        n_ult.append(Fr(counts[i][last]) * cdf_at(cf, last))  # type: ignore[arg-type]
        u_ult.append(Fr(incurred[i][last]) * cdf_at(inf, last))  # type: ignore[arg-type]
        p_rep.append(1 / cdf_at(inf, last))
        freq.append(n_ult[i] / exposure[i])
        sev.append(u_ult[i] / n_ult[i])
        rows += [
            (
                "ultimate_count_N",
                origins[i],
                f(n_ult[i]),
                EXACT,
                f"{counts[i][last]} x {num(cdf_at(cf, last))}",
            ),
            (
                "ultimate_incurred_U",
                origins[i],
                f(u_ult[i]),
                EXACT,
                f"{incurred[i][last]} x {num(cdf_at(inf, last))}",
            ),
            ("incurred_reported_share_p", origins[i], f(p_rep[i]), EXACT, "1 / incurred cdf"),
            (
                "frequency",
                origins[i],
                f(freq[i]),
                EXACT,
                f"N {num(n_ult[i])} / exposure {exposure[i]}",
            ),
            (
                "severity_chain_ladder",
                origins[i],
                f(sev[i]),
                EXACT,
                f"U {num(u_ult[i])} / N {num(n_ult[i])}",
            ),
        ]
    t = np.arange(4, dtype=float)
    slope_f, icpt_f = np.polyfit(t, np.log([float(v) for v in freq]), 1)
    rows += [
        (
            "frequency_trend",
            "slope",
            float(slope_f),
            1e-9,
            "spreadsheet: SLOPE(LN(frequency), t), t = 0..3 (float)",
        ),
        (
            "frequency_trend",
            "intercept",
            float(icpt_f),
            1e-9,
            "INTERCEPT(LN(frequency), t) (float)",
        ),
    ]
    maturity = 0.9
    mature = [i for i in range(4) if float(p_rep[i]) >= maturity]
    assert mature == [0, 1, 2]
    slope_s, icpt_s = np.polyfit(t[mature], np.log([float(sev[i]) for i in mature]), 1)
    rows += [
        (
            "severity_trend",
            "mature_origins_p_at_least_0.9",
            float(len(mature)),
            0.0,
            "origins 2021, 2022, 2023 (p = 1, 0.9895, 0.9609); 2024 has p = 0.8736",
        ),
        (
            "severity_trend",
            "slope",
            float(slope_s),
            1e-9,
            "SLOPE(LN(severity of the mature origins), t) (float)",
        ),
        ("severity_trend", "intercept", float(icpt_s), 1e-9, "INTERCEPT(...) (float)"),
    ]
    total = 0.0
    for i in range(4):
        s_tilde = math.exp(icpt_s + slope_s * t[i])
        ult = float(n_ult[i]) * s_tilde
        total += ult
        rows += [
            ("projected_severity", origins[i], s_tilde, 1e-9, "EXP(intercept + slope t) (float)"),
            (
                "frequency_severity_ultimate",
                origins[i],
                ult,
                1e-9,
                f"N {num(n_ult[i])} x projected severity (float); no catastrophe claims",
            ),
        ]
    rows.append(("frequency_severity_ultimate", "total", total, 1e-9, "sum over origins (float)"))
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT16-frequency-severity-4x4",
            "spec_ids": ["MT16"],
            "kind": "hand_worked",
            "title": "Frequency x severity projection on four origins",
            "source": {"tool": "exact fractions and numpy least squares in Python"},
            "how_produced": (
                f"Run {SCRIPT}. Counts and incurred developed by the volume-weighted chain ladder (tail 1.0), "
                "log-linear trends by ordinary least squares on t = 0..3. maturity_for_trend 0.9, "
                "min_trend_origins 3, no catastrophe claims, nominal amounts (no inflation basis)."
            ),
            "files": {
                "reported_counts": "reported_counts.csv",
                "incurred": "incurred.csv",
                "exposure": "exposure.csv",
                "values": "values.csv",
            },
            "tolerance_note": "1e-12 relative for the rational rows, 1e-9 for rows with logarithms.",
            "notes": [
                "Maturity p of an origin is taken from the incurred chain ladder (the severity measure); "
                "the spec says p_i >= 0.9 without naming the pattern - recorded in decision 0277.",
            ],
        },
    )


# ------------------------------------------------------------------ MT20 credibility A/E


def build_mt20() -> None:
    folder = HAND_TIER_B_DIR / "MT20-credibility-actual-over-expected"
    cells = [
        ("age_30_39", 5000, Fr(21, 10000), 12),
        ("age_40_49", 30000, Fr(3, 1000), 85),
        ("age_50_59", 40000, Fr(7, 1000), 310),
        ("age_60_69", 50000, Fr(14, 1000), 640),
        ("age_70_79", 55000, Fr(2, 100), 1190),
    ]
    write_table(
        folder / "cells.csv",
        ["cell", "central_exposure_life_years", "reference_rate", "actual_deaths"],
        [(c, e, repr(float(r_)), a) for c, e, r_, a in cells],
    )
    prob, tol, conf = 0.9, 0.05, 0.95
    z_fc = float(stats.norm.ppf((1 + prob) / 2))
    n_full = (z_fc / tol) ** 2
    rows: list[tuple] = [
        (
            "limited_fluctuation",
            "z_for_probability",
            z_fc,
            1e-12,
            "NORM.S.INV((1 + 0.9) / 2) (float)",
        ),
        (
            "limited_fluctuation",
            "full_credibility_deaths_nF",
            n_full,
            1e-12,
            "(z / 0.05)^2 (float)",
        ),
    ]
    tot_a = tot_e = 0
    for cell, expo, rate, actual in cells:
        e_c = expo * rate
        tot_a += actual
        tot_e += e_c
        ae = Fr(actual) / e_c
        lo = float(stats.chi2.ppf((1 - conf) / 2, 2 * actual)) / (2 * float(e_c))
        hi = float(stats.chi2.ppf(1 - (1 - conf) / 2, 2 * actual + 2)) / (2 * float(e_c))
        z_c = min(1.0, math.sqrt(actual / n_full))
        rows += [
            ("expected_deaths", cell, f(e_c), EXACT, f"exposure {expo} x rate {num(rate)}"),
            ("actual_over_expected", cell, f(ae), EXACT, f"A {actual} / E {num(e_c)}"),
            ("garwood_lower", cell, lo, 1e-9, "CHISQ.INV(0.025, 2A) / (2E) (float)"),
            ("garwood_upper", cell, hi, 1e-9, "CHISQ.INV(0.975, 2A + 2) / (2E) (float)"),
            ("credibility_Z", cell, z_c, 1e-12, "MIN(1, SQRT(A / nF)) (float)"),
            (
                "credibility_weighted_ae",
                cell,
                z_c * f(ae) + (1 - z_c),
                1e-12,
                "Z x A/E + (1 - Z) x 1 (float)",
            ),
        ]
    ae_all = Fr(tot_a) / tot_e
    lo = float(stats.chi2.ppf((1 - conf) / 2, 2 * tot_a)) / (2 * float(tot_e))
    hi = float(stats.chi2.ppf(1 - (1 - conf) / 2, 2 * tot_a + 2)) / (2 * float(tot_e))
    z_all = min(1.0, math.sqrt(tot_a / n_full))
    rows += [
        ("total", "actual_deaths", float(tot_a), EXACT, "sum"),
        ("total", "expected_deaths", f(tot_e), EXACT, "sum"),
        ("total", "actual_over_expected", f(ae_all), EXACT, "A / E"),
        ("total", "garwood_lower", lo, 1e-9, "float"),
        ("total", "garwood_upper", hi, 1e-9, "float"),
        ("total", "credibility_Z", z_all, 1e-12, "float"),
    ]
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT20-credibility-actual-over-expected",
            "spec_ids": ["MT20"],
            "kind": "hand_worked",
            "title": "Actual over expected with Garwood intervals and limited fluctuation credibility",
            "source": {
                "tool": "exact fractions and scipy.stats (chi-square, normal quantiles)",
                "scipy_version": __import__("scipy").__version__,
            },
            "how_produced": (
                f"Run {SCRIPT}. Five age cells with central exposure, a reference rate and actual deaths. "
                "full_credibility_probability 0.9, tolerance 0.05, confidence 0.95 (the MT20 defaults)."
            ),
            "files": {"cells": "cells.csv", "values": "values.csv"},
            "tolerance_note": "1e-12 relative for exact rows; 1e-9 for chi-square quantiles.",
            "notes": [
                "Buehlmann-Straub credibility is NOT frozen: the spec says the structural parameters are "
                "'estimated from the cells, non-negative' without naming the estimators; a choice changes "
                "the numbers, so it waits for the owner (decision 0272).",
            ],
        },
    )


# ------------------------------------------------------------------ MT21 reinsurance what-if

CLAIMS = [
    # id, sum insured, gross loss, annual premium (all in thousands)
    (1, 250, 45),
    (2, 400, 80),
    (3, 600, 130),
    (4, 600, 210),
    (5, 800, 95),
    (6, 800, 340),
    (7, 1000, 520),
    (8, 1000, 75),
    (9, 1500, 610),
    (10, 2000, 150),
    (11, 2000, 880),
    (12, 2500, 1200),
]


def build_mt21() -> None:
    folder = HAND_TIER_B_DIR / "MT21-reinsurance-twelve-claims"
    premium_rate = Fr(3, 250)  # 1.2 % of the sum insured
    retention_line, lines = 400, 4
    qs_share, qs_commission = Fr(3, 10), Fr(1, 4)
    xl_retention, xl_limit, xl_premium = 100, 200, 40
    write_table(
        folder / "claims.csv",
        ["claim_id", "sum_insured", "gross_loss", "annual_premium"],
        [(c, si, g, repr(float(si * premium_rate))) for c, si, g in CLAIMS],
    )
    rows: list[tuple] = []
    tot = {
        k: Fr(0)
        for k in (
            "gross",
            "qs",
            "sp",
            "xl",
            "prog_sp",
            "prog_qs",
            "prog_xl",
            "p",
            "p_qs",
            "p_sp",
            "p_prog_sp",
            "p_prog_qs",
        )
    }
    for c, si, g in CLAIMS:
        gross = Fr(g)
        prem = si * premium_rate
        tot["gross"] += gross
        tot["p"] += prem
        # 1. quota share alone, on gross
        qs = qs_share * gross
        # 2. surplus alone, on gross
        share = Fr(min(max(si - retention_line, 0), lines * retention_line), si)
        sp = share * gross
        # 3. per-risk excess of loss alone, on gross
        xl = Fr(min(xl_limit, max(0, g - xl_retention)))
        # 4. programme in the inuring order of CV09: surplus, quota share on the retained part, excess of loss on what is left
        prog_sp = share * gross
        after_sp = gross - prog_sp
        prog_qs = qs_share * after_sp
        after_qs = after_sp - prog_qs
        prog_xl = Fr(min(xl_limit, max(0, after_qs - xl_retention)))
        net = after_qs - prog_xl
        assert net == gross - prog_sp - prog_qs - prog_xl
        for k, v in (
            ("qs", qs),
            ("sp", sp),
            ("xl", xl),
            ("prog_sp", prog_sp),
            ("prog_qs", prog_qs),
            ("prog_xl", prog_xl),
        ):
            tot[k] += v
        tot["p_qs"] += qs_share * prem
        tot["p_sp"] += share * prem
        tot["p_prog_sp"] += share * prem
        tot["p_prog_qs"] += qs_share * (prem - share * prem)
        rows += [
            (
                "surplus_cession_share",
                c,
                f(share),
                EXACT,
                f"MIN(MAX(SI - {retention_line}, 0), {lines} x {retention_line}) / SI = {num(share)}",
            ),
            ("quota_share_ceded", c, f(qs), EXACT, f"0.3 x gross {g}"),
            ("surplus_ceded", c, f(sp), EXACT, f"share {num(share)} x gross {g}"),
            (
                "excess_of_loss_ceded",
                c,
                f(xl),
                EXACT,
                f"MIN({xl_limit}, MAX(0, {g} - {xl_retention}))",
            ),
            ("programme_surplus_ceded", c, f(prog_sp), EXACT, "surplus first, on gross"),
            (
                "programme_quota_share_ceded",
                c,
                f(prog_qs),
                EXACT,
                f"0.3 x (gross - surplus) = 0.3 x {num(after_sp)}",
            ),
            (
                "programme_excess_of_loss_ceded",
                c,
                f(prog_xl),
                EXACT,
                f"MIN({xl_limit}, MAX(0, {num(after_qs)} - {xl_retention}))",
            ),
            ("programme_net", c, f(net), EXACT, "gross - surplus - quota share - excess of loss"),
        ]
    quota_premium = qs_share * tot["p"]
    rows += [
        ("total", "gross_loss", f(tot["gross"]), EXACT, "sum"),
        ("total", "quota_share_ceded", f(tot["qs"]), EXACT, "sum"),
        ("total", "surplus_ceded", f(tot["sp"]), EXACT, "sum"),
        ("total", "excess_of_loss_ceded", f(tot["xl"]), EXACT, "sum"),
        ("total", "programme_surplus_ceded", f(tot["prog_sp"]), EXACT, "sum"),
        ("total", "programme_quota_share_ceded", f(tot["prog_qs"]), EXACT, "sum"),
        ("total", "programme_excess_of_loss_ceded", f(tot["prog_xl"]), EXACT, "sum"),
        (
            "total",
            "programme_net",
            f(tot["gross"] - tot["prog_sp"] - tot["prog_qs"] - tot["prog_xl"]),
            EXACT,
            "gross minus the three",
        ),
        ("premium", "gross_premium", f(tot["p"]), EXACT, "1.2 % of the sums insured"),
        ("premium", "quota_share_ceded_premium", f(quota_premium), EXACT, "0.3 x gross premium"),
        (
            "premium",
            "quota_share_commission",
            f(qs_commission * quota_premium),
            EXACT,
            "0.25 x ceded premium",
        ),
        (
            "premium",
            "quota_share_result",
            f(tot["qs"] + qs_commission * quota_premium - quota_premium),
            EXACT,
            "ceded loss + commission - ceded premium",
        ),
        (
            "premium",
            "surplus_ceded_premium",
            f(tot["p_sp"]),
            EXACT,
            "cession share x premium, claim by claim",
        ),
        (
            "premium",
            "surplus_result",
            f(tot["sp"] - tot["p_sp"]),
            EXACT,
            "ceded loss - ceded premium (no commission)",
        ),
        ("premium", "excess_of_loss_premium", float(xl_premium), EXACT, "flat premium, input"),
        (
            "premium",
            "excess_of_loss_result",
            f(tot["xl"] - xl_premium),
            EXACT,
            "ceded loss - premium",
        ),
        (
            "premium",
            "programme_quota_share_ceded_premium",
            f(tot["p_prog_qs"]),
            EXACT,
            "0.3 x premium retained after surplus",
        ),
    ]
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT21-reinsurance-twelve-claims",
            "spec_ids": ["MT21", "CV09"],
            "kind": "hand_worked",
            "title": "Quota share, surplus and per-risk excess of loss on twelve claims, alone and in the CV09 inuring order",
            "source": {"tool": "exact fractions in Python"},
            "how_produced": (
                f"Run {SCRIPT}. Amounts in thousands. Quota share 30 % with 25 % commission; surplus with a "
                "retained line of 400 and four lines; per-risk excess of loss 200 xs 100 at 100 % placed, "
                "flat premium 40. Programme: surplus on gross, quota share on what the surplus leaves, "
                "excess of loss on what the quota share leaves (decision 0604)."
            ),
            "files": {"claims": "claims.csv", "values": "values.csv"},
            "tolerance_note": "1e-12 relative (all rational).",
            "not_covered": [
                "Aggregate deductible and limit, reinstatements with premium, stop loss, event excess of loss "
                "and the index clause: no hand case yet; they belong to the reinsurance item (P30) and the "
                "spec MT21 fixture line stays open for them (decision 0273).",
            ],
        },
    )


# ------------------------------------------------------------------ MT19 Kaplan-Meier


def build_mt19() -> None:
    folder = HAND_TIER_B_DIR / "MT19-kaplan-meier-ten-times"
    data = [(2, 1), (3, 1), (3, 1), (4, 0), (5, 1), (5, 0), (7, 1), (8, 0), (9, 1), (10, 0)]
    write_table(folder / "times.csv", ["time", "event"], data)
    z = float(stats.norm.ppf(0.975))
    rows: list[tuple] = []
    surv = Fr(1)
    green = Fr(0)
    median = None
    for t in sorted({t for t, e in data if e == 1}):
        at_risk = sum(1 for tt, _ in data if tt >= t)
        d = sum(1 for tt, e in data if tt == t and e == 1)
        surv *= Fr(at_risk - d, at_risk)
        green += Fr(d, at_risk * (at_risk - d)) if at_risk > d else 0
        var = surv**2 * green
        se = math.sqrt(float(var))
        # log-log interval: S^exp(+-z sigma / |ln S|), sigma^2 = Greenwood sum
        if float(surv) > 0:
            theta = z * math.sqrt(float(green)) / abs(math.log(float(surv)))
            lo, hi = float(surv) ** math.exp(theta), float(surv) ** math.exp(-theta)
        else:
            lo = hi = 0.0
        rows += [
            ("at_risk", t, float(at_risk), 0.0, f"observations with time >= {t}"),
            ("events", t, float(d), 0.0, "events at the time"),
            ("survival", t, f(surv), EXACT, f"product of (1 - d/n) up to {t}"),
            ("greenwood_sum", t, f(green), EXACT, "sum of d / (n (n - d))"),
            ("greenwood_variance", t, f(var), EXACT, "S^2 x Greenwood sum"),
            ("greenwood_standard_error", t, se, 1e-12, "square root of the variance (float)"),
            (
                "log_log_lower_95",
                t,
                lo,
                1e-9,
                "S ^ EXP(z sigma / |LN S|) with z = 1.959964 (float)",
            ),
            ("log_log_upper_95", t, hi, 1e-9, "S ^ EXP(-z sigma / |LN S|) (float)"),
        ]
        if median is None and surv <= Fr(1, 2):
            median = t
    assert median is not None
    rows.append(("median", "time", float(median), 0.0, "smallest time with S <= 0.5"))
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT19-kaplan-meier-ten-times",
            "spec_ids": ["MT19"],
            "kind": "hand_worked",
            "title": "Kaplan-Meier with censoring and ties, Greenwood variance and log-log interval",
            "source": {
                "tool": "exact fractions in Python; agrees with R survival survfit (tests/benchmarks/tools/check_km_hand_fixture.R)"
            },
            "how_produced": (
                f"Run {SCRIPT}. Ten observations, event 1 / censored 0; two tied events at time 3, a "
                "tied event and censoring at time 5 (the censored observation stays in the risk set at 5)."
            ),
            "files": {"times": "times.csv", "values": "values.csv"},
            "tolerance_note": "1e-12 relative for exact rows; 1e-9 for the interval.",
        },
    )


# ------------------------------------------------------------------ MT18 closed forms


def build_mt18() -> None:
    folder = HAND_TIER_B_DIR / "MT18-gpd-closed-forms"
    n_total, n_exceed, years, u = 2000, 100, 10, 100.0
    cases = [("xi_0.25", 0.25, 50.0), ("xi_0", 0.0, 50.0)]
    rows: list[tuple] = []
    for label, xi, sigma in cases:
        for p in (0.99, 0.995):
            ratio = n_total / n_exceed * (1 - p)
            x_p = u + sigma * (math.log(1 / ratio) if xi == 0 else (ratio ** (-xi) - 1) / xi)
            rows.append(
                (
                    f"quantile_{label}",
                    f"p{p}",
                    x_p,
                    EXACT,
                    f"u + sigma/xi x ((n/N_u (1-p))^-xi - 1) with n/N_u (1-p) = {ratio:.6g}",
                )
            )
            es = x_p / (1 - xi) + (sigma - xi * u) / (1 - xi)
            rows.append(
                (
                    f"expected_shortfall_{label}",
                    f"p{p}",
                    es,
                    EXACT,
                    "x_p/(1-xi) + (sigma - xi u)/(1-xi)",
                )
            )
        for period in (10, 50):
            rate = n_exceed / years * period
            z = u + sigma * (math.log(rate) if xi == 0 else (rate**xi - 1) / xi)
            rows.append(
                (
                    f"return_level_{label}",
                    f"T{period}",
                    z,
                    EXACT,
                    f"u + sigma/xi x ((N_u/h T)^xi - 1) with N_u/h T = {rate:g}",
                )
            )
    for label, pvals in (
        ("rejects_first_three", [0.001, 0.02, 0.05, 0.3, 0.6, 0.8]),
        ("rejects_none", [0.2, 0.3, 0.4]),
    ):
        alpha = 0.1
        stats_ = np.cumsum(-np.log1p(-np.array(pvals))) / np.arange(1, len(pvals) + 1)
        k_hat = max([k for k in range(1, len(pvals) + 1) if stats_[k - 1] <= alpha], default=0)
        rows.append(
            (
                f"forward_stop_{label}",
                "k_hat",
                float(k_hat),
                0.0,
                f"p-values {pvals}, fdr level {alpha}; running means of -ln(1 - p): "
                + ", ".join(f"{v:.6g}" for v in stats_),
            )
        )
        rows.append(
            (
                f"forward_stop_{label}",
                "threshold_index_1_based",
                float(k_hat + 1),
                0.0,
                "next candidate after the rejected ones (lowest when none)",
            )
        )
    mean_excess = [3.0, 7.0, 11.0, 19.0]
    rows.append(
        (
            "xi_zero_scale",
            "mean_excess",
            float(np.mean(mean_excess)),
            EXACT,
            "scale equals the mean excess of 3, 7, 11, 19 when xi is fixed at 0",
        )
    )
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT18-gpd-closed-forms",
            "spec_ids": ["MT18"],
            "kind": "hand_worked",
            "title": "Generalised Pareto quantile, return level and expected shortfall for given parameters",
            "source": {"tool": "plain Python floats"},
            "how_produced": (
                f"Run {SCRIPT}. n = {n_total} claims, N_u = {n_exceed} above u = {u:g}, h = {years} years, "
                "sigma = 50, xi = 0.25 and xi = 0 (the exponential limit)."
            ),
            "files": {"values": "values.csv"},
            "tolerance_note": "1e-12 relative.",
        },
    )


# ------------------------------------------------------------------ MT22 back-test errors


def build_mt22() -> None:
    folder = HAND_TIER_B_DIR / "MT22-back-test-four-origins"
    origins = [2021, 2022, 2023, 2024]
    reference = [1000, 1100, 1200, 1300]
    # ultimate projected at the earlier cut-off, by method and horizon (months)
    estimates = {
        ("chain_ladder", 12): [980, 1130, 1150, 1400],
        ("chain_ladder", 24): [950, 1050, 1300, 1200],
        ("bornhuetter_ferguson", 12): [1000, 1090, 1230, 1280],
        ("bornhuetter_ferguson", 24): [1010, 1120, 1190, 1310],
    }
    write_table(
        folder / "estimates.csv",
        ["method", "horizon_months", *[f"u_{o}" for o in origins]],
        [(m, h, *v) for (m, h), v in estimates.items()],
    )
    write_table(
        folder / "reference.csv",
        ["origin", "reference_ultimate"],
        list(zip(origins, reference, strict=True)),
    )
    rows: list[tuple] = []
    for (method, horizon), est in estimates.items():
        errors = [Fr(e - u, u) for e, u in zip(est, reference, strict=True)]
        weights = [Fr(u) for u in reference]
        total_w = sum(weights)
        bias = sum(w * e for w, e in zip(weights, errors, strict=True)) / total_w
        mae = sum(w * abs(e) for w, e in zip(weights, errors, strict=True)) / total_w
        mse = sum(w * e * e for w, e in zip(weights, errors, strict=True)) / total_w
        label = f"{method}_h{horizon}"
        for o, e, u in zip(origins, errors, reference, strict=True):
            rows.append((f"error_{label}", o, f(e), EXACT, f"(estimate - {u}) / {u}"))
        rows += [
            (
                f"bias_{label}",
                "all",
                f(bias),
                EXACT,
                "sum of w e / sum of w, w = reference ultimate",
            ),
            (f"mae_{label}", "all", f(mae), EXACT, "sum of w |e| / sum of w"),
            (
                f"rmse_{label}",
                "all",
                math.sqrt(float(mse)),
                EXACT,
                "SQRT(sum of w e^2 / sum of w) (float)",
            ),
        ]
    write_values(folder, rows)
    write_manifest(
        folder,
        {
            "id": "MT22-back-test-four-origins",
            "spec_ids": ["MT22", "AE02"],
            "kind": "hand_worked",
            "title": "Back-test errors, bias, mean absolute error and root mean square error",
            "source": {"tool": "exact fractions in Python"},
            "how_produced": (
                f"Run {SCRIPT}. Four origins, two methods at two horizons; the reference is today's "
                "selected ultimate (given). Weights are the reference ultimates."
            ),
            "files": {
                "estimates": "estimates.csv",
                "reference": "reference.csv",
                "values": "values.csv",
            },
            "tolerance_note": "1e-12 relative.",
            "notes": [
                "RMSE is taken as SQRT(sum of w e^2 / sum of w); the spec names RMSE without a formula "
                "(decision 0275).",
            ],
        },
    )


def main() -> None:
    build_mt13()
    build_mt15()
    build_mt16()
    build_mt18()
    build_mt19()
    build_mt20()
    build_mt21()
    build_mt22()
    print("hand fixtures written to", HAND_TIER_B_DIR)


if __name__ == "__main__":
    main()
