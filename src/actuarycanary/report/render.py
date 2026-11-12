"""One self-contained HTML report page (jinja2, plotly inlined once), deterministic byte for byte.

The page is drawn from the report model (`report.model.build_model`) alone: numbers are
rounded there, and figures are plain plotly JSON specifications drawn in the page by the
inlined plotly library. The page makes no network request (decision 0073); the browser's
"print to PDF" gives the printable document through the print stylesheet.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import escape
from plotly.offline import get_plotlyjs

from actuarycanary.report import language

TEMPLATE_DIR = Path(__file__).parent / "templates"
REPORT_NAME = "report.html"


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


def figures_json(figures: dict[str, Any]) -> str:
    """The figures as JSON safe inside a script element."""
    return json.dumps(figures, ensure_ascii=False, allow_nan=False, sort_keys=True).replace(
        "</", "<\\/"
    )


RUN_STATE_MARK = "<!--run-state:{module}-->"


def with_run_states(quality_html: str, runs: dict[str, dict[str, str]]) -> str:
    """The data quality appendix lists, beside the data status of each module, what the module
    did in this run (A1a, R19). The fragment is built before the analysis is at hand, so it
    carries one mark per module that is filled in here."""
    for module, run in runs.items():
        shown = run["state"] + (f": {run['why']}" if run["why"] else "")
        quality_html = quality_html.replace(RUN_STATE_MARK.format(module=module), escape(shown))
    return quality_html


def render_report(model: dict[str, Any], quality_html: str = "", modules_html: str = "") -> str:
    """The page for one run: `quality_html` is the data quality appendix and `modules_html`
    the list of every measure view, both fragments of their own templates."""
    template = _environment().get_template("report.html.j2")
    return template.render(
        m=model,
        quality_html=with_run_states(quality_html, model.get("module_runs", {})),
        modules_html=modules_html,
        figures_json=figures_json(model["figures"]),
        plotly_js=get_plotlyjs(),
    )
