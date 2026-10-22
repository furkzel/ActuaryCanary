"""The modules and measures section of the report page (an HTML fragment the report includes)."""

from functools import cache

import polars as pl
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from actuarycanary.measures.model import MeasureResult
from actuarycanary.modules.runner import AnalysisResult, ModuleState
from actuarycanary.report import numbers
from actuarycanary.report.render import TEMPLATE_DIR

SECTION_TEMPLATE = "modules.html.j2"
MAX_NOTES = 3  # notes shown per measure view; the rest are in modules.json


@cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def headline(result: MeasureResult) -> str:
    """The value of a measure that has one value for everything it covers; otherwise empty."""
    frame = result.frame
    if frame is None or frame.height != 1:
        return numbers.EMPTY
    value = frame["value"][0]
    if value is None:
        return numbers.EMPTY
    return numbers.ratio(value) if result.unit == "ratio" else numbers.amount(float(value))


def _row(result: MeasureResult) -> dict[str, object]:
    notes = result.reason if not result.available else "; ".join(result.notes[:MAX_NOTES])
    frame = result.frame
    flagged = frame.filter(pl.col("note") != "")["note"].n_unique() if frame is not None else 0
    if flagged:
        notes = f"{notes}; {flagged} kinds of row notes".strip("; ")
    return {
        "measure": result.measure,
        "title": result.title,
        "version": result.version,
        "breakdowns": ", ".join(result.request.breakdowns) or "all business",
        "basis": result.request.basis.label(),
        "rows": numbers.count(result.rows) if result.available else "not available",
        "headline": headline(result),
        "notes": notes,
    }


def render_modules_section(analysis: AnalysisResult) -> str:
    modules = [
        {
            "module": m.module,
            "title": m.title,
            "question": m.question,
            "state": m.state.value,
            "reasons": "; ".join(m.reasons),
            "available": len(m.available),
            "measures": [_row(r) for r in m.measures],
        }
        for m in analysis.modules
    ]
    ran = sum(1 for m in analysis.modules if m.state is not ModuleState.SKIPPED)
    return (
        _environment()
        .get_template(SECTION_TEMPLATE)
        .render(modules=modules, ran=ran, total=len(modules))
    )
