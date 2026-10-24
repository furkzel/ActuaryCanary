"""The charts of the report as plain plotly figure specifications, one message per chart.

One visual system (decision 0072): a colour names a segment or a basis and nothing else.
Colours are written as `var(--token)` and resolved by the page from its CSS tokens, so light,
dark and print use the same figures. Paid is one hue and incurred another wherever they
appear, heatmaps included (each on its own one-hue ramp); segments have their own hues; the
selected ultimate is drawn in ink. Ranges are drawn as ranges. Numbers are rounded here (CV06)
so that the figures are stable inputs of the golden test.
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.methods.mack import Mack, applied_to_selected
from actuarycanary.modules.reserving import SELECTION_MEASURE, GroupReserving
from actuarycanary.report import language, numbers
from actuarycanary.report.language import t
from actuarycanary.structures.triangles import THIN_CELL_CLAIMS, Triangle

INK = "var(--text-primary)"
MUTED = "var(--text-muted)"
BASIS_TOKENS = {"paid": "--basis-paid", "incurred": "--basis-incurred"}
SEGMENT_TOKENS = {
    "NON_LIFE": "--segment-non-life",
    "LIFE": "--segment-life",
    "PENSION": "--segment-pension",
    "HEALTH": "--segment-health",
}
METHOD_SYMBOLS = (
    ("chain_ladder", "Chain ladder", "circle"),
    ("bornhuetter_ferguson", "Bornhuetter–Ferguson", "square"),
    ("cape_cod", "Cape Cod", "triangle-up"),
    ("expected_loss_ratio", "Expected loss ratio", "x"),
)
# the central ranges drawn: 5th to 95th percentile, and 25th to 75th inside it
RANGE_PERCENTILES = (0.05, 0.25, 0.75, 0.95)


def basis_colour(measure: str) -> str:
    return f"var({BASIS_TOKENS[measure]})"


def segment_colour(segment: str) -> str:
    return f"var({SEGMENT_TOKENS.get(segment, '--segment-other')})"


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _layout(title: str, x: str, y: str, **extra: Any) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "title": {"text": title},
        "xaxis": {"title": {"text": x}},
        "yaxis": {"title": {"text": y}},
        "showlegend": False,
    }
    if language.current() == language.TURKISH:
        layout["separators"] = ",."  # decimal comma, thousands point
    layout.update(extra)
    return layout


def heatmap(triangle: Triangle, currency: str) -> dict[str, Any]:
    """Cumulative cells by origin and age on the one-hue ramp of the triangle's basis."""
    text = [
        [
            ""
            if not math.isfinite(value)
            else t(
                "{amount} {currency} · {claims} claims",
                amount=numbers.amount(value),
                currency=currency,
                claims=numbers.count(claims),
            )
            + (f" · {t('thin')}" if claims < THIN_CELL_CLAIMS else "")
            for value, claims in zip(row, counts, strict=True)
        ]
        for row, counts in zip(triangle.cumulative, triangle.claim_counts, strict=True)
    ]
    return {
        "data": [
            {
                "type": "heatmap",
                "x": [str(a) for a in triangle.ages],
                "y": list(triangle.origins),
                "z": [[_round(v) for v in row] for row in triangle.cumulative],
                "text": text,
                "hovertemplate": t("Origin %{y} · age %{x} months<br>%{text}<extra></extra>"),
                "xgap": 2,
                "ygap": 2,
                "showscale": False,
                "colorscale": f"ramp:{triangle.measure}",
            }
        ],
        "layout": _layout(
            t("Cumulative {measure}, {currency}", measure=t(triangle.measure), currency=currency),
            t("Development age (months)"),
            t("Origin"),
            xaxis={"title": {"text": t("Development age (months)")}, "type": "category"},
            yaxis={"title": {"text": t("Origin")}, "type": "category", "autorange": "reversed"},
        ),
    }


def factors(group: GroupReserving, measure: str) -> dict[str, Any] | None:
    """Link ratios of every origin per development column and the factor selected."""
    result = group.chain_ladder.get(measure)
    if not isinstance(result, ChainLadder):
        return None
    triangle = group.triangles[measure]
    ages = triangle.ages
    columns = [f"{ages[j]}-{ages[j + 1]}" for j in range(len(ages) - 1)]
    xs: list[str] = []
    ys: list[float | None] = []
    labels: list[str] = []
    for j, column in enumerate(columns):
        for i, origin in enumerate(triangle.origins):
            ratio = float(result.link_ratios[i, j])
            if not math.isfinite(ratio):
                continue
            xs.append(column)
            ys.append(_round(ratio, 4))
            labels.append(
                t("origin {origin}", origin=origin)
                + ("" if result.used[i, j] else f" · {t('excluded')}")
            )
    colour = basis_colour(measure)
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": t("Link ratio of one origin"),
                "x": xs,
                "y": ys,
                "text": labels,
                "marker": {"color": colour, "size": 8, "opacity": 0.7},
                "hovertemplate": "%{x}: %{y:.3f}, %{text}<extra></extra>",
            },
            {
                "type": "scatter",
                "mode": "markers",
                "name": t("Selected factor"),
                "x": columns,
                "y": [_round(float(f), 4) for f in result.factors],
                "marker": {
                    "color": INK,
                    "symbol": "line-ew-open",
                    "size": 26,
                    "line": {"width": 3},
                },
                "hovertemplate": t("%{x}: selected %{y:.3f}<extra></extra>"),
            },
        ],
        "layout": _layout(
            t("Link ratios and the selected factor, {measure}", measure=t(measure)),
            t("Development (months)"),
            t("Factor"),
            showlegend=True,
            xaxis={"title": {"text": t("Development (months)")}, "type": "category"},
        ),
    }


def methods(group: GroupReserving, currency: str) -> dict[str, Any] | None:
    """Ultimate per origin by each method on the selection triangle, beside the selection."""
    found = group.method_ultimates(SELECTION_MEASURE)
    if not found:
        return None
    origins = list(group.triangles[SELECTION_MEASURE].origins)
    colour = basis_colour(SELECTION_MEASURE)
    data: list[dict[str, Any]] = []
    for key, label, symbol in METHOD_SYMBOLS:
        values = found.get(key)
        if values is None:
            continue
        data.append(
            {
                "type": "scatter",
                "mode": "markers",
                "name": t(label),
                "x": [_round(float(v)) for v in values],
                "y": origins,
                "marker": {"color": colour, "symbol": symbol, "size": 9, "opacity": 0.85},
                "hovertemplate": t(
                    "{label}, origin %{y}: %{x:,.0f} {currency}<extra></extra>",
                    label=t(label),
                    currency=currency,
                ),
            }
        )
    selected = group.selected_ultimates()
    if any(v is not None for v in selected):
        data.append(
            {
                "type": "scatter",
                "mode": "markers",
                "name": t("Selected"),
                "x": [_round(v) for v in selected],
                "y": origins,
                "marker": {
                    "color": INK,
                    "symbol": "diamond-open",
                    "size": 15,
                    "line": {"width": 2},
                },
                "hovertemplate": t(
                    "Selected, origin %{y}: %{x:,.0f} {currency}<extra></extra>", currency=currency
                ),
            }
        )
    return {
        "data": data,
        "layout": _layout(
            t(
                "Ultimate by method, {measure}, {currency}",
                measure=t(SELECTION_MEASURE),
                currency=currency,
            ),
            t("Ultimate ({currency})", currency=currency),
            t("Origin"),
            showlegend=True,
            yaxis={"title": {"text": t("Origin")}, "type": "category", "autorange": "reversed"},
        ),
    }


def reserve_range(group: GroupReserving, currency: str) -> dict[str, Any] | None:
    """The Mack range around the selected reserve, per triangle, drawn as a range: the 5th
    to 95th percentile as a light bar, the 25th to 75th as a dark bar inside it, and the
    selected reserve (the mean of the lognormal) as a diamond."""
    rows: list[tuple[str, float, dict[float, float]]] = []
    selected = group.selected_ultimates()
    for measure in ("paid", "incurred"):
        fitted = group.mack.get(measure)
        if not isinstance(fitted, Mack) or None in selected:
            continue
        latest = group.triangles[measure].latest
        reserve = float(np.nansum(np.array(selected, dtype=float) - latest))
        shown = applied_to_selected(
            fitted.total_coefficient_of_variation, reserve, percentiles=RANGE_PERCENTILES
        )
        if shown.range is not None:
            rows.append((measure, reserve, shown.range.percentiles))
    if not rows:
        return None
    data: list[dict[str, Any]] = []
    for measure, reserve, p in rows:
        colour = basis_colour(measure)
        for low, high, width, opacity, label in (
            (0.05, 0.95, 8, 0.35, t("5th to 95th percentile")),
            (0.25, 0.75, 14, 0.9, t("25th to 75th percentile")),
        ):
            data.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "x": [_round(p[low]), _round(p[high])],
                    "y": [t(measure), t(measure)],
                    "line": {"color": colour, "width": width},
                    "opacity": opacity,
                    "hovertemplate": t(
                        "{label}: %{x:,.0f} {currency}<extra></extra>",
                        label=label,
                        currency=currency,
                    ),
                }
            )
        data.append(
            {
                "type": "scatter",
                "mode": "markers",
                "x": [_round(reserve)],
                "y": [t(measure)],
                "marker": {"color": INK, "symbol": "diamond", "size": 11},
                "hovertemplate": t(
                    "Selected reserve: %{x:,.0f} {currency}<extra></extra>", currency=currency
                ),
            }
        )
    return {
        "data": data,
        "layout": _layout(
            t("Selected reserve and its range, {currency}", currency=currency),
            t("Reserve ({currency})", currency=currency),
            t("Triangle"),
            yaxis={"title": {"text": t("Triangle")}, "type": "category"},
            height=200,
        ),
    }


def bars_by_line(
    title: str,
    axis: str,
    rows: Sequence[tuple[str, str, float | None]],
    hover: str,
    limit: float | None = None,
) -> dict[str, Any] | None:
    """Horizontal bars, one per line, in the colour of its segment; `rows` are
    (segment, line, value). An optional limit is drawn as a muted dashed line."""
    shown = [(s, line, v) for s, line, v in rows if v is not None and math.isfinite(v)]
    if not shown:
        return None
    data: list[dict[str, Any]] = [
        {
            "type": "bar",
            "orientation": "h",
            "x": [_round(v, 6) for _, _, v in shown],
            "y": [f"{s} · {line}" for s, line, _ in shown],
            "marker": {"color": [segment_colour(s) for s, _, _ in shown]},
            "hovertemplate": hover,
        }
    ]
    layout = _layout(
        title,
        axis,
        "",
        yaxis={"type": "category", "autorange": "reversed", "automargin": True},
        height=max(160, 60 + 40 * len(shown)),
        margin={"l": 180, "r": 16, "t": 40, "b": 48},
    )
    if limit is not None:
        layout["shapes"] = [
            {
                "type": "line",
                "x0": limit,
                "x1": limit,
                "yref": "paper",
                "y0": 0,
                "y1": 1,
                "line": {"color": MUTED, "dash": "dash", "width": 1.5},
            }
        ]
    return {"data": data, "layout": layout}


def ratio_by_origin(
    title: str, segment: str, points: Sequence[tuple[str, float | None]]
) -> dict[str, Any] | None:
    """One ratio over origin periods for one line, in the colour of its segment."""
    shown = [(o, v) for o, v in points if v is not None and math.isfinite(v)]
    if not shown:
        return None
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "x": [o for o, _ in shown],
                "y": [_round(v, 6) for _, v in shown],
                "line": {"color": segment_colour(segment), "width": 2},
                "marker": {"color": segment_colour(segment), "size": 8},
                "hovertemplate": t("Origin %{x}: %{y:.1%}<extra></extra>"),
            }
        ],
        "layout": _layout(
            title,
            t("Origin"),
            t("Ratio"),
            xaxis={"title": {"text": t("Origin")}, "type": "category"},
            yaxis={"title": {"text": t("Ratio")}, "tickformat": ".0%", "rangemode": "tozero"},
            height=240,
        ),
    }


__all__ = [
    "bars_by_line",
    "basis_colour",
    "factors",
    "heatmap",
    "methods",
    "ratio_by_origin",
    "reserve_range",
    "segment_colour",
]
