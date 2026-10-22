"""Quality output appears in every run: quality.json, the terminal summary and the report."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from actuarycanary.cli import app
from actuarycanary.quality.model import ModuleStatus, QualityReport, Score
from actuarycanary.report.quality_section import render_quality_section
from actuarycanary.report.render import render_report
from tests.report.test_render import _context

BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def run_folder(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    out = tmp_path_factory.mktemp("out")
    result = CliRunner().invoke(app, ["run", str(BASELINE), "--out", str(out)])
    assert result.exit_code == 0, result.output
    return next(out.iterdir()), result.output


def test_run_writes_quality_json_and_records_it_in_the_manifest(
    run_folder: tuple[Path, str],
) -> None:
    folder, _ = run_folder
    body = json.loads((folder / "quality.json").read_text(encoding="utf-8"))
    assert body["scores"]["overall"]["value"] > 90
    assert {c["concept"] for c in body["coverage"]} >= {"claim_valuations", "premiums"}
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert "quality.json" in [o["name"] for o in manifest["outputs"]]
    assert "DQ01" in [s["id"] for s in manifest["specs"]]


def test_terminal_shows_the_quality_summary_before_the_chain_ladder(
    run_folder: tuple[Path, str],
) -> None:
    _, output = run_folder
    assert "Data quality" in output and "DV-CLV-07" in output
    assert output.index("Data quality") < output.index("Chain ladder")


def test_report_starts_with_the_quality_section() -> None:
    section = render_quality_section(_report(), "1.0.0")
    html = render_report(replace(_context(), quality_html=section))
    assert html.index('id="quality"') < html.index('id="summary"')
    assert 'href="#quality"' in html
    assert 'id="quality"' not in render_report(_context())  # no section without a report


def _report() -> QualityReport:
    modules = (ModuleStatus("M04", "Reserving", "unable", ("a<b",)),)
    return QualityReport(None, Score(None, 0), {}, {}, {}, (), (), modules, ())


def test_quality_section_escapes_text_and_names_what_cannot_run() -> None:
    html = render_quality_section(_report(), "1.0.0")
    assert "a&lt;b" in html and "a<b" not in html and "DQ01 v1.0.0" in html
    assert "No finding." in html
