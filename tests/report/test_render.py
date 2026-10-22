"""The report page: offline, labelled, footnoted, printable, deterministic (blueprint 11).

The page is rendered in memory from the model of the shared run; only one slow test reads the
written 5 MB file (tests/test_pipeline.py).
"""

import re

import pytest

from actuarycanary.pipeline import RunResult
from actuarycanary.report.modules_section import render_modules_section
from actuarycanary.report.quality_section import render_quality_section
from actuarycanary.report.render import render_report

pytestmark = pytest.mark.integration

MAX_BYTES = 5_300_000  # about 5 MB: plotly once (4.6 MB) and the run's figures and tables


@pytest.fixture(scope="module")
def html(default_run: RunResult) -> str:
    return render_report(
        default_run.report_data,
        render_quality_section(default_run.quality, "1.0.0"),
        render_modules_section(default_run.analysis),
    )


def _outside_plotly(html: str) -> str:
    """The page without the inlined plotly bundle, whose source names URLs of map traces it
    never loads here (decision 0073)."""
    start = html.index("<script>", html.index("</main>"))
    end = html.index("</script>", start)
    return html[:start] + html[end:]


def test_report_opens_offline_with_no_network_reference(html: str) -> None:
    assert not re.search(r"<(script|img|iframe|link)[^>]+(src|href)=", html)
    assert "@import" not in html and "url(" not in _outside_plotly(html)
    assert not re.search(r"https?://", _outside_plotly(html))
    assert html.count("plotly.js v") == 1  # the library is embedded once


def test_report_size_stays_about_five_megabytes(html: str) -> None:
    assert len(html.encode("utf-8")) < MAX_BYTES


def test_every_analytic_page_carries_the_disclaimer(default_run: RunResult, html: str) -> None:
    model = default_run.report_data
    analytic = 2 + len(model["pages"]) + 1 + len(model["reserving"]["lines"])  # cover too
    assert html.count(model["disclaimer"]) == analytic + 1
    assert model["disclaimer"].startswith("Indicative analysis on the data provided")


def test_every_figure_has_a_footnote_with_spec_versions(default_run: RunResult, html: str) -> None:
    figures = default_run.report_data["figures"]
    assert figures
    for figure_id in figures:
        start = html.index(f'id="{figure_id}"')
        nexts = [i for tag in ("<h3", "<h4", "</section>") if (i := html.find(tag, start)) > 0]
        block = html[start : min(nexts)]
        note = re.search(r'class="footnote">([^<]*)', block)
        assert note and re.search(r"[A-Z]{2}\d{2} v\d+\.\d+\.\d+", note[1]), figure_id


def test_the_page_follows_the_reading_order_of_blueprint_11(html: str) -> None:
    order = [
        'id="cover"',
        'id="findings"',
        'id="glance"',
        'id="portfolio"',
        'id="reserving"',
        'id="line-0"',
        'id="not-run"',
        'id="quality"',
        'id="methods"',
        'id="reproducibility"',
    ]
    positions = [html.index(anchor) for anchor in order]
    assert positions == sorted(positions)


def test_finding_links_point_at_sections_of_the_page(default_run: RunResult, html: str) -> None:
    model = default_run.report_data
    for finding in [*model["key_findings"], *model["further_findings"]]:
        assert f'id="{finding["section"]}"' in html, finding["rule"]


def test_print_stylesheet_gives_the_printable_document(html: str) -> None:
    assert "@media print" in html and "@page" in html
    assert "break-before: page" in html and "beforeprint" in html


def test_page_is_deterministic(default_run: RunResult, html: str) -> None:
    again = render_report(
        default_run.report_data,
        render_quality_section(default_run.quality, "1.0.0"),
        render_modules_section(default_run.analysis),
    )
    assert html == again
