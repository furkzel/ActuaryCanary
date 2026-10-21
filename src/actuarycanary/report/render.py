"""One self-contained HTML report page (jinja2, plotly inlined), deterministic byte for byte.

Figures are written as plain plotly JSON specifications and drawn in the page by the
inlined plotly library; every number shown is rounded here by CV06, hover texts included.
"""

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from plotly.offline import get_plotlyjs

from actuarycanary.canonical.feeds import Finding
from actuarycanary.manifest.run import InputRecord, SpecRecord
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.modules.reserving import GroupReserving, ReservingResult
from actuarycanary.report import numbers
from actuarycanary.structures.triangles import THIN_CELL_CLAIMS, Triangle, TriangleSet

TEMPLATE_DIR = Path(__file__).parent / "templates"
REPORT_NAME = "report.html"
METHODS = ("paid", "incurred")  # chain ladder on the paid and on the incurred triangle


@dataclass(frozen=True)
class ReportContext:
    title: str
    disclaimer: str
    package_version: str
    run_id: str
    reserving: ReservingResult
    findings: tuple[Finding, ...]
    inputs: tuple[InputRecord, ...]
    specs: tuple[SpecRecord, ...]
    settings: dict[str, Any]


@cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _heatmap(triangle: Triangle, currency: str) -> dict[str, Any]:
    ages = [f"{a}" for a in triangle.ages]
    z = [[_finite(v) for v in row] for row in triangle.cumulative]
    text = [
        [
            ""
            if not math.isfinite(value)
            else f"{numbers.amount(value)} {currency} · {numbers.count(claims)} claims"
            + (" · thin" if claims < THIN_CELL_CLAIMS else "")
            for value, claims in zip(row, counts, strict=True)
        ]
        for row, counts in zip(triangle.cumulative, triangle.claim_counts, strict=True)
    ]
    return {
        "data": [
            {
                "type": "heatmap",
                "x": ages,
                "y": list(triangle.origins),
                "z": z,
                "text": text,
                "hovertemplate": "Origin %{y} · age %{x} months<br>%{text}<extra></extra>",
                "xgap": 2,
                "ygap": 2,
                "showscale": False,
            }
        ],
        "layout": {
            "title": {"text": f"Cumulative {triangle.measure}, {currency}"},
            "xaxis": {"title": {"text": "Development age (months)"}, "type": "category"},
            "yaxis": {"title": {"text": "Origin"}, "type": "category", "autorange": "reversed"},
        },
    }


def _factor_rows(group: GroupReserving) -> list[dict[str, str]]:
    ages = group.triangles["paid"].ages
    rows: list[dict[str, str]] = []
    for j in range(len(ages)):
        row = {"from": f"{ages[j]}", "to": f"{ages[j + 1]}" if j + 1 < len(ages) else "ult"}
        for method in METHODS:
            result = group.chain_ladder[method]
            if isinstance(result, ChainLadder):
                last = j == len(ages) - 1
                row[f"{method}_factor"] = numbers.factor(
                    result.tail_factor if last else float(result.factors[j])
                )
                row[f"{method}_cdf"] = numbers.factor(float(result.cdf[j]))
            else:
                row[f"{method}_factor"] = row[f"{method}_cdf"] = numbers.EMPTY
        rows.append(row)
    return rows


def _estimate_rows(group: GroupReserving) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for estimate in [*group.estimates(), group.totals()]:
        ibnr = {m: estimate.ibnr(m) for m in METHODS}
        rows.append(
            {
                "origin": estimate.origin,
                "paid": numbers.amount(estimate.paid),
                "incurred": numbers.amount(estimate.incurred),
                **{f"ult_{m}": numbers.amount(estimate.ultimate[m]) for m in METHODS},
                **{f"ibnr_{m}": numbers.amount(ibnr[m]) for m in METHODS},
                **{f"negative_{m}": (ibnr[m] or 0) < 0 for m in METHODS},
                "total": estimate.origin == "Total",
            }
        )
    return rows


def _triangle_table(triangle: Triangle) -> list[list[str]]:
    return [
        [origin, *[numbers.amount(v) for v in row]]
        for origin, row in zip(triangle.origins, triangle.cumulative, strict=True)
    ]


def _notes(group: GroupReserving) -> list[str]:
    notes: list[str] = []
    for method in METHODS:
        result = group.chain_ladder[method]
        label = f"Chain ladder on {method}"
        if isinstance(result, Skipped):
            notes.append(f"{label} did not run: {result.reason}.")
            continue
        notes += [f"{label}: {w}." for w in result.warnings]
        origins = group.triangles[method].origins
        zero = [origins[i] for i in np.flatnonzero(result.zero_latest)]
        if zero:
            notes.append(
                f"{label}: latest value is zero for {', '.join(zero)}, so the ultimate is zero; "
                "Bornhuetter–Ferguson suits these origins better."
            )
        negative = [origins[i] for i in np.flatnonzero(result.negative)]
        if negative:
            notes.append(
                f"{label}: negative cumulative values for {', '.join(negative)}; "
                "results for these origins are unreliable."
            )
    counts = group.triangles["paid"].claim_counts
    thin = int(((counts >= 0) & (counts < THIN_CELL_CLAIMS)).sum())
    if thin:
        notes.append(f"{thin} cells have fewer than {THIN_CELL_CLAIMS} claims (thin).")
    return notes


def _basis_label(triangles: TriangleSet) -> str:
    settings = triangles.settings
    return f"{settings.reinsurance_basis.value}, {settings.value_basis.value}"


def render_report(context: ReportContext) -> str:
    triangles = context.reserving.triangles
    currency = triangles.reporting_currency
    groups = []
    figures: dict[str, Any] = {}
    for n, group in enumerate(context.reserving.groups):
        ids = {m: f"heatmap-{n}-{m}" for m in METHODS}
        for measure, figure_id in ids.items():
            figures[figure_id] = _heatmap(group.triangles[measure], currency)
        totals = group.totals()
        groups.append(
            {
                "anchor": f"group-{n}",
                "name": " · ".join(group.group),
                "figure_ids": ids,
                "factors": _factor_rows(group),
                "estimates": _estimate_rows(group),
                "triangles": {m: _triangle_table(group.triangles[m]) for m in METHODS},
                "ages": list(group.triangles["paid"].ages),
                "notes": _notes(group),
                "summary": {
                    "paid": numbers.amount(totals.paid),
                    "incurred": numbers.amount(totals.incurred),
                    **{f"ult_{m}": numbers.amount(totals.ultimate[m]) for m in METHODS},
                    "ibnr_incurred": numbers.amount(totals.ibnr("incurred")),
                },
            }
        )
    not_converted = [
        {
            "currency": row["currency"],
            "claims": numbers.count(row["claims"]),
            "paid": numbers.amount(row["paid"]),
            "incurred": numbers.amount(row["incurred"]),
        }
        for row in triangles.not_converted.iter_rows(named=True)
    ]
    specs = {s.id: s for s in context.specs}
    template = _environment().get_template("report.html.j2")
    return template.render(
        title=context.title,
        disclaimer=context.disclaimer,
        version=context.package_version,
        run_id=context.run_id,
        cut_off=triangles.cut_off.isoformat(),
        currency=currency,
        origin_basis=triangles.origin_basis,
        basis_label=_basis_label(triangles),
        value_date=triangles.value_date.isoformat() if triangles.value_date else None,
        price_index=triangles.price_index,
        settings=triangles.settings,
        chain_ladder=context.reserving.settings,
        claims_used=numbers.count(triangles.claims_used),
        proxy_claims=numbers.count(triangles.proxy_claims),
        groups=groups,
        not_converted=not_converted,
        findings=context.findings,
        inputs=context.inputs,
        specs=context.specs,
        spec=lambda spec_id: f"{spec_id} v{specs[spec_id].version}",
        figures_json=json.dumps(
            figures, ensure_ascii=False, allow_nan=False, sort_keys=True
        ).replace("</", "<\\/"),
        plotly_js=get_plotlyjs(),
    )


def write_report(folder: Path, context: ReportContext) -> Path:
    path = folder / REPORT_NAME
    path.write_text(render_report(context), encoding="utf-8", newline="\n")
    return path
