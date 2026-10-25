"""Severity distribution fitting with goodness of fit (MT17).

Lognormal, gamma, Weibull and Pareto II (Lomax) are fitted by maximum likelihood to the claim
sizes of each group, location fixed at zero. Closed claims (final sizes) are used by default;
open claims enter at their incurred when `claims_used` is "all_non_nil", and the two fits can be
compared. A truncation point conditions the likelihood on X > d. Each family gets standard
errors, AIC, BIC, Kolmogorov-Smirnov and Anderson-Darling statistics with parametric-bootstrap
p-values (on a seeded subsample of at most `gof_max_claims` claims, record 0615), and plot
data. The family with the lowest AIC among those the Anderson-Darling test does not reject is
selected; its quantiles, limited expected values and layer costs are reported.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.methods.diagnostics import WARNING, Diagnostic, thin_evidence
from actuarycanary.methods.severity import families as fam
from actuarycanary.methods.severity import gof
from actuarycanary.methods.severity.sizes import (
    ALL_NON_NIL,
    CLOSED_CLAIMS,
    GROUP_BY,
    SEED,
    GroupSizes,
    group_rng,
    group_sizes,
    severity_trend,
)

METHOD = "MT17"
QUANTILE_LEVELS = (0.50, 0.75, 0.90, 0.95, 0.99, 0.995)
DEFAULT_CANDIDATES = fam.FAMILIES
GOF_BOOTSTRAP = 200
GOF_MAX_CLAIMS = 2000
SIGNIFICANCE = 0.05
MIN_CLAIMS = 50
SELECTED_BY_AIC = "lowest AIC among the families the Anderson-Darling test does not reject"
NO_FAMILY_FITS = "no family fits"
NOT_FITTED = "not fitted"


@dataclass(frozen=True)
class SeverityFits:
    parameters: pl.DataFrame  # group, family, parameter, estimate, std_error
    fits: pl.DataFrame  # group, family: loglik, aic, bic, ranks, D, A2, p-values, status
    selected: pl.DataFrame  # group: selected family, why, claims
    quantiles: pl.DataFrame  # group, family, probability, quantile
    limited_expected_values: pl.DataFrame  # group, family, limit, lev, layer, layer cost
    plots: pl.DataFrame  # group, family: probability, empirical/fitted quantile and survival
    trend: pl.DataFrame  # group, origin_year: claims, mean, median
    trend_summary: pl.DataFrame  # group: annual change of ln size, standard error, p-value
    groups: pl.DataFrame  # group: claims used, claim set, status, reason
    diagnostics: tuple[Diagnostic, ...]
    seed: int
    options: Mapping[str, Any] = field(default_factory=dict)

    def randomness(self) -> list[dict[str, object]]:
        return [
            {
                "method": METHOD,
                "seed": self.seed,
                "purpose": "bootstrap p-values and the subsample of the goodness-of-fit tests",
            }
        ]


def _label(key: Sequence[str]) -> str:
    return " / ".join(key)


def _layers(limits: Sequence[float]) -> list[tuple[float, float]]:
    """(retention, upper bound) of the consecutive layers cut by the sorted limits; the last
    layer (upper bound infinity) is the part above the highest limit."""
    edges = [0.0, *sorted(limits)]
    return [*zip(edges[:-1], edges[1:], strict=True), (edges[-1], math.inf)]


def fit_severity(
    sizes: pl.DataFrame,
    *,
    candidates: Sequence[str] = DEFAULT_CANDIDATES,
    claims_used: str = CLOSED_CLAIMS,
    truncation_point: float = 0.0,
    exclude_catastrophes: bool = True,
    gof_bootstrap: int = GOF_BOOTSTRAP,
    gof_max_claims: int = GOF_MAX_CLAIMS,
    significance: float = SIGNIFICANCE,
    min_claims: int = MIN_CLAIMS,
    limits: Sequence[float] = (),
    seed: int = SEED,
    group_by: Sequence[str] = GROUP_BY,
) -> SeverityFits:
    """MT17 on a frame of claim sizes (see `sizes.group_sizes`)."""
    for name in candidates:
        if name not in fam.FAMILIES:
            raise fam.FamilyError(f"unknown family {name!r}; allowed: {', '.join(fam.FAMILIES)}")
    if any(not math.isfinite(v) or v <= 0 for v in limits):
        raise ValueError("limits must be positive numbers")
    if truncation_point < 0:
        raise ValueError("truncation_point cannot be negative")
    group_by = list(group_by)
    groups = group_sizes(
        sizes,
        claims_used=claims_used,
        catastrophes="exclude" if exclude_catastrophes else "keep",
        group_by=group_by,
    )
    tables: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "parameters",
            "fits",
            "selected",
            "quantiles",
            "lev",
            "plots",
            "trend",
            "trend_summary",
            "groups",
        )
    }
    diagnostics: list[Diagnostic] = []
    for group in groups:
        _fit_group(
            group,
            group_by,
            tables,
            diagnostics,
            candidates=list(candidates),
            claims_used=claims_used,
            truncation=truncation_point,
            n_boot=gof_bootstrap,
            max_claims=gof_max_claims,
            significance=significance,
            min_claims=min_claims,
            limits=list(limits),
            seed=seed,
        )
    return SeverityFits(
        parameters=_frame(tables["parameters"], group_by),
        fits=_frame(tables["fits"], group_by),
        selected=_frame(tables["selected"], group_by),
        quantiles=_frame(tables["quantiles"], group_by),
        limited_expected_values=_frame(tables["lev"], group_by),
        plots=_frame(tables["plots"], group_by),
        trend=_frame(tables["trend"], group_by),
        trend_summary=_frame(tables["trend_summary"], group_by),
        groups=_frame(tables["groups"], group_by),
        diagnostics=tuple(diagnostics),
        seed=seed,
        options={
            "candidates": list(candidates),
            "claims_used": claims_used,
            "truncation_point": truncation_point,
            "exclude_catastrophes": exclude_catastrophes,
            "gof_bootstrap": gof_bootstrap,
            "gof_max_claims": gof_max_claims,
            "significance": significance,
            "min_claims": min_claims,
            "limits": list(limits),
        },
    )


def _frame(rows: list[dict[str, Any]], group_by: Sequence[str]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema={g: pl.String for g in group_by})
    return pl.DataFrame(rows, infer_schema_length=None)


def _fit_group(
    group: GroupSizes,
    group_by: list[str],
    tables: dict[str, list[dict[str, Any]]],
    diagnostics: list[Diagnostic],
    *,
    candidates: list[str],
    claims_used: str,
    truncation: float,
    n_boot: int,
    max_claims: int,
    significance: float,
    min_claims: int,
    limits: list[float],
    seed: int,
) -> None:
    where = dict(zip(group_by, group.key, strict=True))
    label = _label(group.key)
    x_all = group.sizes
    x = x_all[x_all > truncation] if truncation > 0 else x_all
    n = len(x)
    base = {"claims_used": claims_used, "claims": n, "truncation_point": truncation}
    if n < min_claims:
        reason = f"{n} claims, fewer than {min_claims}"
        tables["groups"].append({**where, **base, "status": NOT_FITTED, "reason": reason})
        tables["selected"].append(
            {**where, "family": None, "why": NOT_FITTED, "claims": n, "reason": reason}
        )
        diagnostics.append(
            Diagnostic(METHOD, "NOT_FITTED", WARNING, f"{label}: {reason}", label, n)
        )
        return
    tables["groups"].append({**where, **base, "status": "fitted", "reason": ""})

    years = group.years
    by_year, summary = severity_trend(x_all, years)
    for row in by_year.iter_rows(named=True):
        tables["trend"].append({**where, **row})
    tables["trend_summary"].append({**where, "years": by_year.height, **summary})
    thin = thin_evidence(METHOD, by_year.height, "origin years") if by_year.height else None
    if thin:
        diagnostics.append(
            Diagnostic(METHOD, thin.code, WARNING, f"{label}: {thin.message}", label, thin.value)
        )
    if summary["p_value"] < 0.01 and not math.isnan(summary["annual_change"]):
        diagnostics.append(
            Diagnostic(
                METHOD,
                "SEVERITY_TREND",
                WARNING,
                f"{label}: sizes at value-date prices change by {summary['annual_change']:+.1%} "
                f"a year (p = {summary['p_value']:.3g}); pooled origin years mix levels, "
                "which widens the fitted distribution (superimposed inflation)",
                label,
                summary["annual_change"],
            )
        )

    rng_subsample = group_rng(seed, group.key, 1)
    if n > max_claims:
        pick = np.sort(rng_subsample.choice(n, size=max_claims, replace=False))
        subsample = x[pick]
    else:
        subsample = x

    estimates: dict[str, fam.Estimate] = {}
    gofs: dict[str, gof.Gof | None] = {}
    for index, name in enumerate(candidates):
        est = fam.estimate(name, x, truncation)
        estimates[name] = est
        gofs[name] = None
        if not est.converged:
            reason = _why_not_converged(name, est)
            diagnostics.append(
                Diagnostic(METHOD, "NO_CONVERGENCE", WARNING, f"{label}: {reason}", label)
            )
            continue
        a_sub, b_sub, ok = fam.mle(name, subsample, truncation)
        if ok:
            gofs[name] = gof.goodness_of_fit(
                name,
                subsample,
                a_sub,
                b_sub,
                n_boot,
                group_rng(seed, group.key, 10 + index),
                truncation,
            )
        if name == fam.PARETO and est.a <= 1.0:
            diagnostics.append(
                Diagnostic(
                    METHOD,
                    "INFINITE_MEAN",
                    WARNING,
                    f"{label}: infinite mean (Pareto shape {est.a:.3g} at or below 1); only "
                    "limited expected values are given",
                    label,
                    est.a,
                )
            )

    usable = [name for name in candidates if estimates[name].converged]
    aic_rank = {
        name: r + 1 for r, name in enumerate(sorted(usable, key=lambda m: estimates[m].aic))
    }
    bic_rank = {
        name: r + 1 for r, name in enumerate(sorted(usable, key=lambda m: estimates[m].bic))
    }
    rejected = {name for name in usable if (g := gofs[name]) is not None and g.ad_p < significance}
    pool = [name for name in usable if name not in rejected]
    if not usable:
        chosen, why = None, NOT_FITTED
    elif pool:
        chosen, why = min(pool, key=lambda m: estimates[m].aic), SELECTED_BY_AIC
    else:
        chosen, why = min(usable, key=lambda m: estimates[m].aic), NO_FAMILY_FITS
        diagnostics.append(
            Diagnostic(
                METHOD,
                "NO_FAMILY_FITS",
                WARNING,
                f"{label}: every family is rejected by the Anderson-Darling test at "
                f"{significance:g}; {chosen} has the lowest AIC and is shown as the best of "
                "poor fits",
                label,
            )
        )
    for name in candidates:
        est = estimates[name]
        g = gofs[name]
        first, second = fam.PARAMETER_NAMES[name]
        for pname, value, se in ((first, est.a, est.a_se), (second, est.b, est.b_se)):
            tables["parameters"].append(
                {**where, "family": name, "parameter": pname, "estimate": value, "std_error": se}
            )
        tables["fits"].append(
            {
                **where,
                "family": name,
                "claims": n,
                "loglik": est.loglik,
                "aic": est.aic,
                "bic": est.bic,
                "aic_rank": aic_rank.get(name),
                "bic_rank": bic_rank.get(name),
                "ks": None if g is None else g.ks,
                "ad": None if g is None else g.ad,
                "ks_p": None if g is None else g.ks_p,
                "ad_p": None if g is None else g.ad_p,
                "gof_claims": None if g is None else g.n_used,
                "gof_bootstrap": None if g is None else g.n_boot,
                "converged": est.converged,
                "rejected": name in rejected,
                "selected": name == chosen,
            }
        )
        if est.converged:
            tables["plots"].extend(
                {**where, "family": name, **row} for row in _plot_rows(name, x, est, truncation)
            )
    tables["selected"].append(
        {
            **where,
            "family": chosen,
            "why": why,
            "claims": n,
            "reason": "",
            "aic": None if chosen is None else estimates[chosen].aic,
        }
    )
    if chosen is None:
        return
    best = estimates[chosen]
    for p in QUANTILE_LEVELS:
        tables["quantiles"].append(
            {
                **where,
                "family": chosen,
                "probability": p,
                "quantile": float(fam.ppf(chosen, p, best.a, best.b)),
            }
        )
    if limits:
        _layer_costs(chosen, best, sorted({float(L) for L in limits}), where, tables["lev"])


def _layer_costs(
    chosen: str,
    best: fam.Estimate,
    limits: list[float],
    where: dict[str, str],
    out: list[dict[str, Any]],
) -> None:
    """One row per layer cut by the limits: E[X ^ L] at its upper bound and the cost of the
    layer, E[X ^ upper] - E[X ^ retention]; the last row is the part above the highest limit
    (its limited expected value is the mean, NaN when the mean is infinite)."""
    lev = {0.0: 0.0} | {L: fam.limited_expected_value(chosen, L, best.a, best.b) for L in limits}
    mean = _full_mean(chosen, best.a, best.b) if fam.mean_is_finite(chosen, best.a) else math.nan
    for lower, upper in _layers(limits):
        top = mean if math.isinf(upper) else lev[upper]
        out.append(
            {
                **where,
                "family": chosen,
                "layer_retention": lower,
                "limit": None if math.isinf(upper) else upper,
                "limited_expected_value": top,
                "layer_cost": top - lev[lower],
                "survival_at_limit": None
                if math.isinf(upper)
                else float(fam.sf(chosen, np.array([upper]), best.a, best.b)[0]),
            }
        )


def _full_mean(family: str, a: float, b: float) -> float:
    if family == fam.LOGNORMAL:
        return math.exp(a + b * b / 2.0)
    if family == fam.GAMMA:
        return a * b
    if family == fam.WEIBULL:
        return b * math.gamma(1.0 + 1.0 / a)
    return b / (a - 1.0)


def _why_not_converged(name: str, est: fam.Estimate) -> str:
    if name == fam.PARETO and est.a > 1e5:
        return (
            "Pareto shape tends to infinity (the sizes are lighter-tailed than any Pareto II; "
            "the limit is the exponential): left out of selection"
        )
    return f"{name}: the optimiser did not converge: left out of selection"


def _plot_rows(
    name: str, x: np.ndarray, est: fam.Estimate, truncation: float
) -> list[dict[str, float]]:
    data = gof.plot_data(name, x, est.a, est.b, truncation)
    return [{k: float(v[j]) for k, v in data.items()} for j in range(len(data["probability"]))]


def compare_claim_sets(sizes: pl.DataFrame, **options: Any) -> dict[str, SeverityFits]:
    """The fit on closed claims and on all non-nil claims side by side (MT17 assumption: sizes
    of closed claims are final, the incurred of open claims is an estimate)."""
    options.pop("claims_used", None)
    return {
        CLOSED_CLAIMS: fit_severity(sizes, claims_used=CLOSED_CLAIMS, **options),
        ALL_NON_NIL: fit_severity(sizes, claims_used=ALL_NON_NIL, **options),
    }
