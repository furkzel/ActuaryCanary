"""The settlement-speed part of the M03 page (MT19, record 0341): Kaplan–Meier curves by line
with their intervals, the 25th, 50th and 75th percentile of the time to settlement, the share
censored by report year with the log-rank test, the hazard ratios of the Cox model with the
thin-evidence warnings, and the information-only outputs labelled as such.

Numbers are cells of the `survival_*.csv` files; curves are drawn from the rows of
`survival_curves.csv` (at most 400 per curve, every row an exact point of the curve).
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import polars as pl

from actuarycanary.report import numbers
from actuarycanary.report.charts import _layout, _round, segment_colour
from actuarycanary.report.frames import of_segment, p_value, table, text, value
from actuarycanary.report.language import t

LINE = "line"
PERCENTILES = (0.25, 0.5, 0.75)


def _curve_figure(rows: list[dict[str, Any]], segment: str, name: str) -> dict[str, Any]:
    times = [_round(value(r["time"]), 1) for r in rows]
    colour = segment_colour(segment)
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "x": times,
                "y": [_round(value(r["upper"]), 4) for r in rows],
                "line": {"color": colour, "width": 0, "shape": "hv"},
                "hoverinfo": "skip",
            },
            {
                "type": "scatter",
                "mode": "lines",
                "x": times,
                "y": [_round(value(r["lower"]), 4) for r in rows],
                "line": {"color": colour, "width": 0, "shape": "hv"},
                "fill": "tonexty",
                "fillcolor": colour,
                "opacity": 0.25,
                "hoverinfo": "skip",
            },
            {
                "type": "scatter",
                "mode": "lines",
                "x": times,
                "y": [_round(value(r["survival"]), 4) for r in rows],
                "line": {"color": colour, "width": 2, "shape": "hv"},
                "hovertemplate": t("%{x:,.0f} days: %{y:.1%} still open<extra></extra>"),
            },
        ],
        "layout": _layout(
            t("Share of claims still open by days since report, {line}", line=name),
            t("Days since report"),
            t("Still open"),
            yaxis={"title": {"text": t("Still open")}, "range": [0, 1], "tickformat": ".0%"},
            height=260,
        ),
    }


def _percentiles(rows: Sequence[dict[str, Any]], grouping: str, group: str) -> list[str]:
    found = {
        value(r["percentile"]): r
        for r in rows
        if r["grouping"] == grouping and str(r["group"]) == group
    }
    out = []
    for p in PERCENTILES:
        r = found.get(p)
        if r is None:
            out.append(numbers.EMPTY)
            continue
        if value(r["time"]) is None:
            out.append(t("beyond observed range"))
            continue
        low, high = value(r["lower"]), value(r["upper"])
        out.append(
            f"{numbers.count(value(r['time']))} ({numbers.count(low)}–"
            f"{numbers.count(high) if high is not None else t('beyond observed range')})"
        )
    return out


def survival_page(
    tables: Mapping[str, pl.DataFrame],
    information: Sequence[str],
    diagnostics: Sequence[dict[str, str]],
    spec: Callable[..., str],
    figures: dict[str, Any],
) -> dict[str, Any] | None:
    groups = table(tables, "survival_groups.csv")
    if not groups.height:
        return None
    curves = table(tables, "survival_curves.csv")
    percentiles = table(tables, "survival_time_percentiles.csv")
    segments = list(dict.fromkeys(groups["segment"].to_list()))
    lines = []
    for segment in segments:
        rows = [r for r in of_segment(groups, segment) if r["grouping"] == LINE]
        for r in rows:
            group = str(r["group"])
            mine = [
                c
                for c in of_segment(curves, segment)
                if c["grouping"] == LINE and str(c["group"]) == group
            ]
            figure_id = f"survival-{segment}-{group}".lower().replace("_", "-")
            if mine:
                figures[figure_id] = _curve_figure(mine, segment, group)
            lines.append(
                {
                    "line": f"{segment} · {group}",
                    "claims": numbers.count(value(r["claims"])),
                    "events": numbers.count(value(r["events"])),
                    "censored": numbers.ratio(value(r["share_censored"])),
                    "month_end": numbers.count(value(r["month_end_dates"])),
                    "status": text(r["status"]),
                    "thin": r["status"] != "ok",
                    "percentiles": _percentiles(of_segment(percentiles, segment), LINE, group),
                    "figure": figure_id if mine else "",
                }
            )
    models = [
        {
            "segment": r["segment"],
            "status": text(r["status"]),
            "reason": text(r["reason"]),
            "covariates": text(r["covariates"]),
            "claims": numbers.count(value(r["claims"])),
            "events": numbers.count(value(r["events"])),
            "lr_p": p_value(r["likelihood_ratio_p"]),
            "wald_p": p_value(r["wald_p"]),
            "concordance": numbers.factor(value(r["concordance"])),
            "note": text(r["note"]),
        }
        for r in table(tables, "survival_cox_models.csv").to_dicts()
    ]
    coefficients = [
        {
            "segment": r["segment"],
            "term": text(r["term"]),
            "reference": text(r["reference"]),
            "events": numbers.count(value(r["events"])),
            "ratio": numbers.factor(value(r["hazard_ratio"])),
            "low": numbers.factor(value(r["hazard_ratio_lower"])),
            "high": numbers.factor(value(r["hazard_ratio_upper"])),
            "p": p_value(r["p_value"]),
        }
        for r in table(tables, "survival_cox_coefficients.csv").to_dicts()
    ]
    proportional = [
        {
            "segment": r["segment"],
            "term": text(r["term"]),
            "statistic": numbers.factor(value(r["statistic"])),
            "p": p_value(r["p_value"]),
        }
        for r in table(tables, "survival_proportional_hazards_test.csv").to_dicts()
    ]
    cohorts = table(tables, "survival_cohorts.csv")
    cohort_rows = [
        {
            "segment": r["segment"],
            "year": str(r["report_year"]),
            "claims": numbers.count(value(r["claims"])),
            "censored": numbers.ratio(value(r["share_censored"])),
        }
        for r in cohorts.to_dicts()
    ]
    logrank = [
        {
            "segment": r["segment"],
            "statistic": numbers.factor(value(r["logrank_statistic"])),
            "df": numbers.count(value(r["logrank_df"])),
            "p": p_value(r["logrank_p"]),
        }
        for r in cohorts.to_dicts()
        if value(r["logrank_statistic"]) is not None
    ]
    return {
        "lines": lines,
        "models": models,
        "coefficients": coefficients,
        "proportional": proportional,
        "cohorts": cohort_rows,
        "logrank": logrank,
        "information": list(information),
        "warnings": [d for d in diagnostics if d["severity"] != "INFO"],
        "footnotes": {
            "curves": t(
                "Kaplan–Meier estimate of the share of claims still open by days since report, "
                "with the Greenwood log-log interval at 95% ({spec}); the event is the first "
                "closing, a claim open at the valuation date is censored. Rows of "
                "survival_curves.csv and survival_time_percentiles.csv; a percentile the curve "
                "does not reach is beyond the observed range.",
                spec=spec("MT19", "CL08"),
            ),
            "cox": t(
                "Cox proportional hazards by segment ({spec}): a hazard ratio below 1 settles "
                "slower than the reference level. Rows of survival_cox_models.csv and "
                "survival_cox_coefficients.csv.",
                spec=spec("MT19"),
            ),
            "information": t(
                "Information only, with no frozen reference yet (record 0616): the "
                "Grambsch–Therneau test of proportional hazards, the concordance and the "
                "baseline survival (survival_proportional_hazards_test.csv, "
                "survival_schoenfeld_residuals.csv, survival_baseline.csv). The size class at "
                "the cut-off is a descriptive grouping only."
            ),
        },
    }


__all__ = ["survival_page"]
