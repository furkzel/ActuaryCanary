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
from plotly.offline import get_plotlyjs

TEMPLATE_DIR = Path(__file__).parent / "templates"
REPORT_NAME = "report.html"


@cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def figures_json(figures: dict[str, Any]) -> str:
    """The figures as JSON safe inside a script element."""
    return json.dumps(figures, ensure_ascii=False, allow_nan=False, sort_keys=True).replace(
        "</", "<\\/"
    )


def render_report(model: dict[str, Any], quality_html: str = "", modules_html: str = "") -> str:
    """The page for one run: `quality_html` is the data quality appendix and `modules_html`
    the list of every measure view, both fragments of their own templates."""
    template = _environment().get_template("report.html.j2")
    return template.render(
        m=model,
        quality_html=quality_html,
        modules_html=modules_html,
        figures_json=figures_json(model["figures"]),
        plotly_js=get_plotlyjs(),
    )
