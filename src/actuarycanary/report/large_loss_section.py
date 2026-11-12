"""The large-loss part of the M06 page (record 0340): the severity families fitted by MT17
with the selection, the large-loss threshold of CV08 beside the extreme-value threshold of
MT18 with the claims and incurred above each, the exceedances per year, the generalised Pareto
fit with its tail quantiles and return levels, and the reasons where a fit did not run.

The CV08 threshold classes the claims (record 0601); the MT18 threshold is shown beside it and
classes nothing. Numbers are cells of `severity_*.csv` and `extreme_*.csv`.
"""

from collections.abc import Callable, Mapping
from typing import Any

import polars as pl

from actuarycanary.methods.severity.fitting import NO_FAMILY_FITS
from actuarycanary.report import numbers
from actuarycanary.report.charts import _layout, segment_colour
from actuarycanary.report.frames import of_line, p_value, table, text, value
from actuarycanary.report.language import t

FAMILIES = {
    "lognormal": "lognormal",
    "gamma": "gamma",
    "weibull": "Weibull",
    "pareto": "Pareto II",
}
QUANTILES = (0.5, 0.9, 0.99, 0.995)
INFINITE_VARIANCE = 0.5  # a generalised Pareto shape at or above this has no finite variance
INFINITE_MEAN = 1.0  # and at or above this no finite mean


def _lines(tables: Mapping[str, pl.DataFrame]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name in ("severity_groups.csv", "extreme_threshold_comparison.csv"):
        frame = table(tables, name)
        if frame.height:
            found += [(r["segment"], r["line"]) for r in frame.select("segment", "line").to_dicts()]
    return list(dict.fromkeys(found))


def fits(tables: Mapping[str, pl.DataFrame], segment: str, line: str) -> dict[str, Any]:
    groups = of_line(table(tables, "severity_groups.csv"), segment, line)
    group = groups[0] if groups else {}
    selected = of_line(table(tables, "severity_selected.csv"), segment, line)
    chosen = selected[0] if selected else {}
    no_fit = text(chosen.get("why")) == NO_FAMILY_FITS
    rows = [
        {
            "family": t(FAMILIES.get(str(r["family"]), str(r["family"]))),
            "aic": numbers.amount(value(r["aic"])),
            "bic": numbers.amount(value(r["bic"])),
            "ks_p": p_value(r["ks_p"]),
            "ad_p": p_value(r["ad_p"]),
            "rejected": bool(r["rejected"]),
            "converged": bool(r["converged"]),
            "selected": bool(r["selected"]) and not no_fit,
        }
        for r in of_line(table(tables, "severity_fits.csv"), segment, line)
    ]
    family = text(chosen.get("family"))
    quantiles = {
        value(r["probability"]): value(r["quantile"])
        for r in of_line(table(tables, "severity_quantiles.csv"), segment, line)
        if r["family"] == family
    }
    return {
        "claims": numbers.count(value(group.get("claims"))),
        "status": text(group.get("status")),
        "reason": text(group.get("reason")),
        "rows": rows,
        "family": t(FAMILIES.get(family, family)) if family else "",
        "why": text(chosen.get("why")),
        # every family rejected: the file keeps the lowest-AIC family and its quantiles, the page
        # shows none of them (A1a, R17, record 0753)
        "no_fit": no_fit,
        "quantiles": [numbers.amount(quantiles.get(q)) for q in QUANTILES],
    }


def thresholds(tables: Mapping[str, pl.DataFrame], segment: str, line: str) -> dict[str, Any]:
    comparison = of_line(table(tables, "extreme_threshold_comparison.csv"), segment, line)
    found = of_line(table(tables, "extreme_thresholds.csv"), segment, line)
    c = comparison[0] if comparison else {}
    th = found[0] if found else {}
    return {
        "cv08": numbers.amount(value(c.get("cv08_threshold"))),
        "cv08_claims": numbers.count(value(c.get("claims_at_or_above_cv08"))),
        "cv08_incurred": numbers.ratio(value(c.get("incurred_share_cv08"))),
        "mt18": numbers.amount(value(c.get("extreme_value_threshold"))),
        "mt18_claims": numbers.count(value(c.get("claims_above_extreme_value"))),
        "mt18_incurred": numbers.ratio(value(c.get("incurred_share_extreme_value"))),
        "quantile": numbers.ratio(value(th.get("quantile"))),
        "status": text(th.get("status")),
        "reason": text(th.get("reason")) or text(c.get("note")),
    }


def tail(tables: Mapping[str, pl.DataFrame], segment: str, line: str) -> dict[str, Any] | None:
    gpd = of_line(table(tables, "extreme_gpd_fit.csv"), segment, line)
    if not gpd:
        return None
    g = gpd[0]
    xi = value(g["xi"])
    warning = ""
    if xi is not None and xi >= INFINITE_MEAN:
        warning = t("the fitted shape is 1 or more: the fitted tail has no finite mean")
    elif xi is not None and xi >= INFINITE_VARIANCE:
        warning = t("the fitted shape is 0.5 or more: the fitted tail has no finite variance")
    quantiles = [
        {
            "probability": numbers.ratio(value(r["probability"])),
            "quantile": numbers.amount(value(r["quantile"])),
            "shortfall": numbers.amount(value(r["expected_shortfall"])),
        }
        for r in of_line(table(tables, "extreme_tail_quantiles.csv"), segment, line)
    ]
    returns = [
        {
            "period": numbers.count(value(r["return_period"])),
            "level": numbers.amount(value(r["return_level"])),
            "years": numbers.count(value(r["years_of_data"])),
        }
        for r in of_line(table(tables, "extreme_return_levels.csv"), segment, line)
    ]
    summary = of_line(table(tables, "extreme_yearly_summary.csv"), segment, line)
    s = summary[0] if summary else {}
    return {
        "xi": numbers.factor(xi),
        "xi_low": numbers.factor(value(g["xi_interval_low"])),
        "xi_high": numbers.factor(value(g["xi_interval_high"])),
        "sigma": numbers.amount(value(g["sigma"])),
        "exceedances": numbers.count(value(g["exceedances"])),
        "warning": warning,
        "quantiles": quantiles,
        "returns": returns,
        "dispersion": numbers.factor(value(s.get("dispersion_index"))),
        "dispersion_p": p_value(s.get("dispersion_p_value")),
        "trend": numbers.change_ratio(value(s.get("excess_trend_annual_change"))),
        "trend_p": p_value(s.get("excess_trend_p_value")),
    }


def yearly_figure(
    tables: Mapping[str, pl.DataFrame], segment: str, line: str
) -> dict[str, Any] | None:
    rows = of_line(table(tables, "extreme_yearly.csv"), segment, line)
    if not rows:
        return None
    return {
        "data": [
            {
                "type": "bar",
                "x": [str(r["origin_year"]) for r in rows],
                "y": [int(value(r["exceedances"]) or 0) for r in rows],
                "marker": {"color": segment_colour(segment)},
                "hovertemplate": t("%{x}: %{y} claims above the threshold<extra></extra>"),
            }
        ],
        "layout": _layout(
            t("Claims above the extreme-value threshold by origin year, {line}", line=line),
            t("Origin year"),
            t("Claims"),
            xaxis={"title": {"text": t("Origin year")}, "type": "category"},
            height=240,
        ),
    }


def large_loss_page(
    tables: Mapping[str, pl.DataFrame],
    spec: Callable[..., str],
    figures: dict[str, Any],
    currency: str,
) -> dict[str, Any]:
    lines = []
    for n, (segment, line) in enumerate(_lines(tables)):
        figure_id = f"large-loss-yearly-{n}"
        figure = yearly_figure(tables, segment, line)
        if figure is not None:
            figures[figure_id] = figure
        lines.append(
            {
                "line": f"{segment} · {line}",
                "fits": fits(tables, segment, line),
                "thresholds": thresholds(tables, segment, line),
                "tail": tail(tables, segment, line),
                "figure": figure_id if figure is not None else "",
            }
        )
    return {
        "lines": lines,
        "currency": currency,
        "quantile_headers": [numbers.ratio(q) for q in QUANTILES],
        "footnotes": {
            "fits": t(
                "Severity families fitted by maximum likelihood to the claim sizes CV08 classes "
                "({spec}); Kolmogorov–Smirnov and Anderson–Darling p-values by bootstrap; the "
                "selected family has the lowest AIC among those the Anderson–Darling test does "
                "not reject. Rows of severity_fits.csv, severity_selected.csv and "
                "severity_quantiles.csv.",
                spec=spec("MT17", "CV08"),
            ),
            "thresholds": t(
                "The large-loss threshold of the run is CV08's ({cv08}); the extreme-value "
                "threshold of MT18 ({mt18}, ForwardStop over the candidate quantiles) is shown "
                "beside it and classes no claim (record 0601). Rows of "
                "extreme_threshold_comparison.csv and extreme_thresholds.csv.",
                cv08=spec("CV08"),
                mt18=spec("MT18"),
            ),
            "tail": t(
                "Generalised Pareto fit above the extreme-value threshold with the profile "
                "interval of the shape; tail quantiles with the expected shortfall, and return "
                "levels per number of years ({spec}). Rows of extreme_gpd_fit.csv, "
                "extreme_tail_quantiles.csv, extreme_return_levels.csv and "
                "extreme_yearly_summary.csv.",
                spec=spec("MT18"),
            ),
        },
    }


__all__ = ["large_loss_page"]
