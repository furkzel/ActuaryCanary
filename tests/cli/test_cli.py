from pathlib import Path

import pytest
from typer.testing import CliRunner

from actuarycanary import __version__
from actuarycanary.cli import app
from actuarycanary.manifest.metadata import load_metadata

runner = CliRunner()


def test_info_prints_project_name() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert load_metadata().name in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"


@pytest.mark.integration
def test_run_writes_report_and_manifest(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(BASELINE), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Run id" in result.output
    assert len(list(tmp_path.glob("*/report.html"))) == 1
    assert len(list(tmp_path.glob("*/manifest.json"))) == 1


def test_run_without_claim_valuations_fails_with_a_message(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(tmp_path), "--out", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "claim_valuations.xlsx" in result.output


def test_run_rejects_incompatible_periods(tmp_path: Path) -> None:
    arguments = ["run", str(tmp_path), "--origin-period", "quarter", "--development-period", "year"]
    result = runner.invoke(app, arguments)
    assert result.exit_code == 2
    assert "whole multiple" in result.output
