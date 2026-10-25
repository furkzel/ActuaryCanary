"""Extreme value analysis by peaks over threshold (MT18).

The excesses over a threshold u are fitted by a generalised Pareto distribution. The threshold of
a group is chosen by ForwardStop (Bader, Yan and Zhang 2018) on Anderson-Darling bootstrap
p-values at candidate empirical quantiles of the sizes; the fit gives tail quantiles, return
levels and expected shortfall.

The threshold selected here is used only inside this fit. It is reported next to the large-loss
threshold of CV08 in force, with the share of claims and of incurred above each, and never
decides which claims are LARGE (record 0601). A group without a candidate that has
`min_exceedances` excesses is not run: there is no fallback inside MT18, and the large-loss
views keep the CV08 threshold.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl
from scipy import stats

from actuarycanary.methods.diagnostics import WARNING, Diagnostic, thin_evidence
from actuarycanary.methods.severity import gpd
from actuarycanary.methods.severity.sizes import (
    ALL_NON_NIL,
    GROUP_BY,
    SEED,
    GroupSizes,
    Key,
    group_rng,
    group_sizes,
    severity_trend,
)

METHOD = "MT18"
INFO = "INFO"
CANDIDATE_QUANTILES = (0.80, 0.825, 0.85, 0.875, 0.90, 0.925, 0.95, 0.96, 0.97, 0.975, 0.98, 0.99)
MIN_EXCEEDANCES = 50
MIN_EXCEEDANCES_FLOOR = 10  # a generalised Pareto fit needs at least this many excesses
FDR_LEVEL = 0.10
GOF_BOOTSTRAP = 500
RETURN_PERIODS = (10, 50, 100, 200)
TAIL_PROBABILITIES = (0.99, 0.995, 0.999)
MEAN_EXCESS_LEVELS = tuple(round(0.50 + 0.01 * k, 2) for k in range(50))  # 0.50 to 0.99
MEAN_EXCESS_MIN = 10  # fewest excesses behind a point of the mean excess plot
QQ_POINTS = 200
OVERDISPERSION_SIGNIFICANCE = 0.01
NOT_RUN = "not run"
FITTED = "fitted"


@dataclass(frozen=True)
class ExtremeValues:
    thresholds: pl.DataFrame  # group: status, reason, selected u, ForwardStop k-hat
    candidates: pl.DataFrame  # group, quantile, u, N_u, xi, sigma, modified scale, p-value, path
    gpd_fit: pl.DataFrame  # group: xi, sigma, standard errors, profile interval of xi
    tail_quantiles: pl.DataFrame  # group, probability: x_p, expected shortfall
    return_levels: pl.DataFrame  # group, return period: z_T
    threshold_comparison: pl.DataFrame  # selected u beside the CV08 threshold
    mean_excess: pl.DataFrame  # group, u, N_u, mean excess, standard error
    excess_plot: pl.DataFrame  # quantile plot of the excesses of the selected threshold
    yearly: pl.DataFrame  # group, origin year: exceedances and their sizes
    yearly_summary: pl.DataFrame  # group: dispersion test of the yearly counts, size trend
    diagnostics: tuple[Diagnostic, ...]
    seed: int
    options: Mapping[str, Any] = field(default_factory=dict)

    def randomness(self) -> list[dict[str, object]]:
        return [
            {
                "method": METHOD,
                "seed": self.seed,
                "purpose": "Anderson-Darling bootstrap p-values of the threshold candidates",
            }
        ]


def forward_stop(
    p_values: Sequence[float], fdr_level: float = FDR_LEVEL
) -> tuple[int, list[float]]:
    """ForwardStop: k-hat is the largest k whose running mean of -ln(1 - p) is at most the false
    discovery rate; the first k-hat candidates (lowest thresholds) are rejected and the next one
    is chosen (index k-hat, counting from 0; k-hat equals the number of candidates when all are
    rejected). Returns k-hat and the running means."""
    running: list[float] = []
    total = 0.0
    k_hat = 0
    for k, p in enumerate(p_values, start=1):
        total += -math.log1p(-min(p, 1.0 - 1e-16))
        running.append(total / k)
        if running[-1] <= fdr_level:
            k_hat = k
    return k_hat, running


def candidate_thresholds(
    x: np.ndarray, quantiles: Sequence[float], min_exceedances: int
) -> list[tuple[float, float, int]]:
    """(quantile level, threshold u, excesses) of the candidates that are tried: u is the
    empirical quantile of the sizes (linear interpolation) and a size is an excess when it is
    strictly above u; a candidate with fewer than `min_exceedances` excesses is not tried."""
    if len(x) == 0:
        return []
    found = []
    for q in quantiles:
        u = float(np.quantile(x, q))
        count = int(np.sum(x > u))
        if count >= min_exceedances:
            found.append((q, u, count))
    return found


def _label(key: Key) -> str:
    return " / ".join(key)


def _share(sizes: np.ndarray, above: np.ndarray) -> tuple[int, float, float]:
    total = float(sizes.sum())
    return (
        int(above.sum()),
        float(above.mean()) if len(above) else math.nan,
        float(sizes[above].sum() / total) if total > 0 else math.nan,
    )


def extreme_values(
    sizes: pl.DataFrame,
    *,
    cv08_thresholds: Mapping[Key, float | None] | None = None,
    candidate_quantiles: Sequence[float] = CANDIDATE_QUANTILES,
    min_exceedances: int = MIN_EXCEEDANCES,
    fdr_level: float = FDR_LEVEL,
    gof_bootstrap: int = GOF_BOOTSTRAP,
    return_periods: Sequence[float] = RETURN_PERIODS,
    claims_used: str = ALL_NON_NIL,
    years: float | None = None,
    seed: int = SEED,
    group_by: Sequence[str] = GROUP_BY,
) -> ExtremeValues:
    """MT18 on a frame of claim sizes (see `sizes.group_sizes`).

    `cv08_thresholds` maps a group key to the large-loss threshold in force (CV08 or its
    override); `years` replaces the span of origin years found in the data (h in the return
    levels)."""
    if not candidate_quantiles or any(not 0.0 < q < 1.0 for q in candidate_quantiles):
        raise ValueError("candidate_quantiles must be probabilities between 0 and 1")
    if min_exceedances < MIN_EXCEEDANCES_FLOOR:
        raise ValueError(f"min_exceedances must be at least {MIN_EXCEEDANCES_FLOOR}")
    if any(t <= 0 for t in return_periods):
        raise ValueError("return_periods must be positive")
    group_by = list(group_by)
    groups = group_sizes(sizes, claims_used=claims_used, catastrophes="events", group_by=group_by)
    rows: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "thresholds",
            "candidates",
            "gpd_fit",
            "tail_quantiles",
            "return_levels",
            "comparison",
            "mean_excess",
            "excess_plot",
            "yearly",
            "yearly_summary",
        )
    }
    diagnostics: list[Diagnostic] = []
    thresholds = dict(cv08_thresholds or {})
    for group in groups:
        _run_group(
            group,
            group_by,
            rows,
            diagnostics,
            cv08=thresholds.get(group.key),
            quantiles=list(candidate_quantiles),
            min_exceedances=min_exceedances,
            fdr_level=fdr_level,
            n_boot=gof_bootstrap,
            periods=list(return_periods),
            years=years,
            seed=seed,
        )

    def frame(name: str) -> pl.DataFrame:
        if not rows[name]:
            return pl.DataFrame(schema={g: pl.String for g in group_by})
        return pl.DataFrame(rows[name], infer_schema_length=None)

    return ExtremeValues(
        thresholds=frame("thresholds"),
        candidates=frame("candidates"),
        gpd_fit=frame("gpd_fit"),
        tail_quantiles=frame("tail_quantiles"),
        return_levels=frame("return_levels"),
        threshold_comparison=frame("comparison"),
        mean_excess=frame("mean_excess"),
        excess_plot=frame("excess_plot"),
        yearly=frame("yearly"),
        yearly_summary=frame("yearly_summary"),
        diagnostics=tuple(diagnostics),
        seed=seed,
        options={
            "candidate_quantiles": list(candidate_quantiles),
            "min_exceedances": min_exceedances,
            "fdr_level": fdr_level,
            "gof_bootstrap": gof_bootstrap,
            "return_periods": list(return_periods),
            "claims_used": claims_used,
            "years": years,
        },
    )


def _run_group(
    group: GroupSizes,
    group_by: list[str],
    rows: dict[str, list[dict[str, Any]]],
    diagnostics: list[Diagnostic],
    *,
    cv08: float | None,
    quantiles: list[float],
    min_exceedances: int,
    fdr_level: float,
    n_boot: int,
    periods: list[float],
    years: float | None,
    seed: int,
) -> None:
    where = dict(zip(group_by, group.key, strict=True))
    label = _label(group.key)
    x = group.sizes
    n = len(x)

    tried = [(q, u) for q, u, _ in candidate_thresholds(x, quantiles, min_exceedances)]
    if not tried:
        reason = (
            f"{n} claims; no candidate threshold leaves {min_exceedances} excesses "
            f"(lowest candidate quantile {min(quantiles):g})"
        )
        rows["thresholds"].append(
            {**where, "status": NOT_RUN, "reason": reason, "claims": n, "events": group.n_events}
        )
        diagnostics.append(Diagnostic(METHOD, "NOT_RUN", WARNING, f"{label}: {reason}", label, n))
        rows["comparison"].extend(_comparison(where, x, None, cv08, "extreme-value fit not run"))
        return

    fits: list[tuple[float, float, np.ndarray, gpd.GpdFit | None, float, float]] = []
    for index, (q, u) in enumerate(tried):
        excess = x[x > u] - u
        fitted = gpd.fit(excess)
        if fitted.xi < gpd.MIN_XI or fitted.boundary:
            fits.append((q, u, excess, None, math.nan, math.nan))
            diagnostics.append(
                Diagnostic(
                    METHOD,
                    "CANDIDATE_SKIPPED",
                    INFO,
                    f"{label}: threshold at quantile {q:g} skipped: xi {fitted.xi:.3g} is below "
                    f"{gpd.MIN_XI} or the likelihood has no interior maximum",
                    label,
                    q,
                )
            )
            continue
        ad, p = gpd.bootstrap_p_value(
            excess, fitted, n_boot, group_rng(seed, group.key, 100 + index)
        )
        fits.append((q, u, excess, fitted, ad, p))

    valid = [i for i, f in enumerate(fits) if f[3] is not None]
    if not valid:
        reason = "the generalised Pareto fit failed at every candidate threshold"
        rows["thresholds"].append(
            {**where, "status": NOT_RUN, "reason": reason, "claims": n, "events": group.n_events}
        )
        diagnostics.append(Diagnostic(METHOD, "NOT_RUN", WARNING, f"{label}: {reason}", label, n))
        rows["comparison"].extend(_comparison(where, x, None, cv08, "extreme-value fit not run"))
        return
    p_values = [fits[i][5] for i in valid]
    k_hat, path = forward_stop(p_values, fdr_level)
    all_rejected = k_hat >= len(valid)
    chosen = valid[min(k_hat, len(valid) - 1)]
    q_sel, u_sel, excess, fit_sel, _, _ = fits[chosen]
    assert fit_sel is not None
    n_exceed = len(excess)
    if all_rejected:
        diagnostics.append(
            Diagnostic(
                METHOD,
                "ALL_REJECTED",
                WARNING,
                f"{label}: the generalised Pareto fit is rejected at every candidate threshold "
                f"(ForwardStop at {fdr_level:g}); the highest threshold (quantile {q_sel:g}) is "
                "shown and its fit is poor",
                label,
                q_sel,
            )
        )

    se_xi, se_sigma = gpd.standard_errors_of(excess, fit_sel)
    ci_low, ci_high = gpd.profile_interval(excess, fit_sel)
    path_by_candidate = dict(zip(valid, path, strict=True))
    for i, (q, u, ex, f, ad, p) in enumerate(fits):
        row: dict[str, Any] = {
            **where,
            "quantile": q,
            "threshold": u,
            "exceedances": len(ex),
            "skipped": f is None,
            "selected": i == chosen,
            "rejected_by_forward_stop": i in valid and valid.index(i) < k_hat,
        }
        if f is not None:
            se = gpd.standard_errors_of(ex, f)
            row |= {
                "xi": f.xi,
                "xi_std_error": se[0],
                "sigma": f.sigma,
                "sigma_std_error": se[1],
                "modified_scale": f.sigma - f.xi * u,
                "ad": ad,
                "p_value": p,
                "forward_stop_mean": path_by_candidate.get(i),
            }
        rows["candidates"].append(row)

    rows["thresholds"].append(
        {
            **where,
            "status": FITTED,
            "reason": "all candidates rejected: highest threshold shown" if all_rejected else "",
            "claims": n,
            "events": group.n_events,
            "quantile": q_sel,
            "threshold": u_sel,
            "exceedances": n_exceed,
            "forward_stop_k_hat": k_hat,
            "fdr_level": fdr_level,
        }
    )
    rows["gpd_fit"].append(
        {
            **where,
            "threshold": u_sel,
            "exceedances": n_exceed,
            "xi": fit_sel.xi,
            "xi_std_error": se_xi,
            "xi_interval_low": ci_low,
            "xi_interval_high": ci_high,
            "sigma": fit_sel.sigma,
            "sigma_std_error": se_sigma,
            "modified_scale": fit_sel.sigma - fit_sel.xi * u_sel,
            "loglik": fit_sel.loglik,
        }
    )
    if fit_sel.xi >= 1.0:
        diagnostics.append(
            Diagnostic(
                METHOD,
                "INFINITE_MEAN_TAIL",
                WARNING,
                f"{label}: infinite mean tail (xi {fit_sel.xi:.3g} at or above 1); quantiles are "
                "shown, expected shortfall is not",
                label,
                fit_sel.xi,
            )
        )
    for p in TAIL_PROBABILITIES:
        x_p = gpd.tail_quantile(p, u_sel, fit_sel.xi, fit_sel.sigma, n, n_exceed)
        rows["tail_quantiles"].append(
            {
                **where,
                "probability": p,
                "quantile": x_p,
                "expected_shortfall": gpd.expected_shortfall(x_p, u_sel, fit_sel.xi, fit_sel.sigma),
            }
        )

    known = group.years[np.isfinite(group.years)]
    h = (
        years
        if years is not None
        else (float(known.max() - known.min() + 1) if len(known) else None)
    )
    if h is None:
        diagnostics.append(
            Diagnostic(
                METHOD,
                "NO_YEARS",
                INFO,
                f"{label}: no origin years, so return levels are not given",
                label,
            )
        )
    else:
        for t in periods:
            rows["return_levels"].append(
                {
                    **where,
                    "return_period": t,
                    "years_of_data": h,
                    "return_level": gpd.return_level(
                        t, u_sel, fit_sel.xi, fit_sel.sigma, n_exceed, h
                    ),
                }
            )
        thin = thin_evidence(METHOD, int(h), "origin years")
        if thin:
            diagnostics.append(
                Diagnostic(
                    METHOD, thin.code, WARNING, f"{label}: {thin.message}", label, thin.value
                )
            )

    rows["comparison"].extend(_comparison(where, x, u_sel, cv08, ""))
    _mean_excess(where, x, rows["mean_excess"])
    _excess_plot(where, excess, fit_sel, rows["excess_plot"])
    _yearly(group, where, u_sel, label, rows, diagnostics)


def _comparison(
    where: dict[str, str], x: np.ndarray, u: float | None, cv08: float | None, note: str
) -> list[dict[str, Any]]:
    """The selected u beside the CV08 threshold, with claims and incurred above each. A size
    above u is an excess (strictly above); CV08 classes a claim LARGE at or above its threshold."""
    nan = (None, None, None)
    claims_u, share_u, incurred_u = _share(x, x > u) if u is not None else nan
    claims_c, share_c, incurred_c = _share(x, x >= cv08) if cv08 is not None else nan
    return [
        {
            **where,
            "extreme_value_threshold": u,
            "claims_above_extreme_value": claims_u,
            "claim_share_extreme_value": share_u,
            "incurred_share_extreme_value": incurred_u,
            "cv08_threshold": cv08,
            "claims_at_or_above_cv08": claims_c,
            "claim_share_cv08": share_c,
            "incurred_share_cv08": incurred_c,
            "note": note,
        }
    ]


def _mean_excess(where: dict[str, str], x: np.ndarray, out: list[dict[str, Any]]) -> None:
    for level in MEAN_EXCESS_LEVELS:
        u = float(np.quantile(x, level))
        excess = x[x > u] - u
        if len(excess) < MEAN_EXCESS_MIN:
            continue
        out.append(
            {
                **where,
                "quantile": level,
                "threshold": u,
                "exceedances": len(excess),
                "mean_excess": float(excess.mean()),
                "std_error": float(excess.std(ddof=1) / math.sqrt(len(excess))),
            }
        )


def _excess_plot(
    where: dict[str, str], excess: np.ndarray, fitted: gpd.GpdFit, out: list[dict[str, Any]]
) -> None:
    m = min(QQ_POINTS, len(excess))
    probability = (np.arange(1, m + 1) - 0.5) / m
    empirical = np.quantile(excess, probability, method="hazen")
    model = gpd.ppf(probability, fitted.xi, fitted.sigma)
    out.extend(
        {
            **where,
            "probability": float(probability[j]),
            "empirical_excess": float(empirical[j]),
            "fitted_excess": float(model[j]),
        }
        for j in range(m)
    )


def _yearly(
    group: GroupSizes,
    where: dict[str, str],
    u: float,
    label: str,
    rows: dict[str, list[dict[str, Any]]],
    diagnostics: list[Diagnostic],
) -> None:
    """Exceedances per origin year (roughly Poisson) and their sizes by year (no trend)."""
    known = np.isfinite(group.years)
    if known.sum() == 0:
        return
    years = group.years[known].astype(np.int64)
    sizes = group.sizes[known]
    all_years = np.arange(years.min(), years.max() + 1)
    counts = np.array([int(np.sum((years == y) & (sizes > u))) for y in all_years])
    claims = np.array([int(np.sum(years == y)) for y in all_years])
    for y, c, k in zip(all_years, counts, claims, strict=True):
        above = sizes[(years == y) & (sizes > u)]
        rows["yearly"].append(
            {
                **where,
                "origin_year": int(y),
                "claims": int(k),
                "exceedances": int(c),
                "mean_excess": float((above - u).mean()) if len(above) else None,
            }
        )
    mean = counts.mean()
    dispersion = float(counts.var(ddof=1) / mean) if len(counts) > 1 and mean > 0 else math.nan
    p_value = (
        float(stats.chi2.sf(dispersion * (len(counts) - 1), len(counts) - 1))
        if not math.isnan(dispersion)
        else math.nan
    )
    exceed_mask = sizes > u
    _, trend = severity_trend(sizes[exceed_mask] - u, years[exceed_mask].astype(float))
    rows["yearly_summary"].append(
        {
            **where,
            "years": len(all_years),
            "dispersion_index": dispersion,
            "dispersion_p_value": p_value,
            "excess_trend_annual_change": trend["annual_change"],
            "excess_trend_p_value": trend["p_value"],
        }
    )
    if not math.isnan(p_value) and p_value < OVERDISPERSION_SIGNIFICANCE:
        diagnostics.append(
            Diagnostic(
                METHOD,
                "OVERDISPERSED_EXCEEDANCES",
                WARNING,
                f"{label}: yearly counts of exceedances vary more than a Poisson count "
                f"(dispersion {dispersion:.2f}, p = {p_value:.3g}); return levels may be too "
                "narrow",
                label,
                dispersion,
            )
        )
    if trend["p_value"] < OVERDISPERSION_SIGNIFICANCE:
        diagnostics.append(
            Diagnostic(
                METHOD,
                "EXCESS_TREND",
                WARNING,
                f"{label}: exceedance sizes at value-date prices change by "
                f"{trend['annual_change']:+.1%} a year (p = {trend['p_value']:.3g}); the pooled "
                "excesses are not identically distributed",
                label,
                trend["annual_change"],
            )
        )
