"""The modules and measures section of the report page (an HTML fragment the report includes)."""

from functools import cache

import polars as pl
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from actuarycanary.measures.model import MeasureResult
from actuarycanary.modules.runner import AnalysisResult, ModuleState
from actuarycanary.report import language, numbers
from actuarycanary.report.language import t
from actuarycanary.report.render import TEMPLATE_DIR
from actuarycanary.spec.catalogue import SpecCatalogue

SECTION_TEMPLATE = "modules.html.j2"
MAX_NOTES = 3  # notes shown per measure view; the rest are in modules.json


@cache
def _environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.globals.update(tr=language.t, trh=language.th)
    return environment


def module_title(catalogue: SpecCatalogue | None, module: str, english: str) -> str:
    """The module's title in the language of the report."""
    found = catalogue.modules.get(module) if catalogue is not None else None
    if found is not None and language.current() == language.TURKISH:
        return found.title_tr
    return english


def headline(result: MeasureResult) -> str:
    """The value of a measure that has one value for everything it covers; otherwise empty."""
    frame = result.frame
    if frame is None or frame.height != 1 or "value" not in frame.columns:
        return numbers.EMPTY
    value = frame["value"][0]
    if value is None:
        return numbers.EMPTY
    return numbers.ratio(value) if result.unit == "ratio" else numbers.amount(float(value))


def _row(result: MeasureResult, catalogue: SpecCatalogue | None) -> dict[str, object]:
    spec = catalogue.measures.get(result.measure) if catalogue is not None else None
    title = (
        spec.title_tr
        if spec is not None and language.current() == language.TURKISH
        else result.title
    )
    notes = result.reason if not result.available else "; ".join(result.notes[:MAX_NOTES])
    frame = result.frame
    flagged = frame.filter(pl.col("note") != "")["note"].n_unique() if frame is not None else 0
    if flagged:
        notes = f"{notes}; {t('{n} kinds of row notes', n=flagged)}".strip("; ")
    return {
        "measure": result.measure,
        "title": title,
        "version": result.version,
        "breakdowns": ", ".join(t(b) for b in result.request.breakdowns) or t("all business"),
        "basis": ", ".join(t(p) for p in result.request.basis.label().split(", ")),
        "rows": numbers.count(result.rows) if result.available else t("not available"),
        "headline": headline(result),
        "notes": notes,
    }


def render_modules_section(analysis: AnalysisResult, catalogue: SpecCatalogue | None = None) -> str:
    modules = [
        {
            "module": m.module,
            "title": module_title(catalogue, m.module, m.title),
            "question": t(m.question),
            "state": t(m.state.value),
            "state_code": m.state.value,
            "reasons": "; ".join(t(x) for x in m.reasons),
            "available": len(m.available),
            "measures": [_row(r, catalogue) for r in m.measures],
        }
        for m in analysis.modules
    ]
    ran = sum(1 for m in analysis.modules if m.state is not ModuleState.SKIPPED)
    return (
        _environment()
        .get_template(SECTION_TEMPLATE)
        .render(modules=modules, ran=ran, total=len(modules))
    )
