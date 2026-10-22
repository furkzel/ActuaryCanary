import shutil
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


MESSY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "messy_headers"
SHEETS = 7  # six files, market on two sheets


@pytest.mark.integration
@pytest.mark.slow
def test_messy_run_asks_once_saves_profiles_and_then_does_not_ask(tmp_path: Path) -> None:
    arguments = ["run", str(MESSY), "--out", str(tmp_path / "out")]
    arguments += ["--profiles", str(tmp_path / "profiles")]
    first = runner.invoke(app, arguments, input="a\n" * SHEETS)
    assert first.exit_code == 0, first.output
    assert f"{SHEETS} sheet(s) have a layout without a saved mapping profile" in first.output
    assert first.output.count("Accept, edit or skip") == SHEETS
    assert "HASARR NO" in first.output and "fuzzy" in first.output
    assert len(list((tmp_path / "profiles").glob("*.yaml"))) == SHEETS

    second = runner.invoke(app, arguments)  # no input: a question would fail the run
    assert second.exit_code == 0, second.output
    assert "Accept, edit or skip" not in second.output
    assert "saved" in second.output and "TCKN" in second.output


@pytest.mark.integration
def test_new_layouts_without_answers_or_yes_stop_with_a_message(tmp_path: Path) -> None:
    arguments = ["run", str(MESSY), "--out", str(tmp_path / "out")]
    result = runner.invoke(app, [*arguments, "--profiles", str(tmp_path / "profiles")])
    assert result.exit_code == 1
    assert "--yes" in result.output
    assert not (tmp_path / "profiles").exists()


@pytest.mark.integration
def test_yes_uses_the_proposals_without_saving_or_asking(tmp_path: Path) -> None:
    arguments = ["run", str(MESSY), "--out", str(tmp_path / "out"), "--yes"]
    result = runner.invoke(app, [*arguments, "--profiles", str(tmp_path / "profiles")])
    assert result.exit_code == 0, result.output
    assert "Accept, edit or skip" not in result.output
    assert "automatic" in result.output
    assert not (tmp_path / "profiles").exists()


@pytest.mark.integration
def test_edits_are_saved_in_the_profile(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(MESSY / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    arguments = ["run", str(folder), "--out", str(tmp_path / "out")]
    arguments += ["--profiles", str(tmp_path / "profiles")]
    answers = "e\n3=-\nx=y\n\n"  # leave column 3 (RUCU TAHSILAT) unused; one bad command
    result = runner.invoke(app, arguments, input=answers)
    assert result.exit_code == 0, result.output
    assert "Not understood" in result.output
    (profile,) = (tmp_path / "profiles").glob("*.yaml")
    text = profile.read_text(encoding="utf-8")
    assert "header: 'RUCU TAHSILAT '\n  field: null\n  layer: user" in text


@pytest.mark.integration
def test_run_lists_which_modules_ran_and_why_others_did_not(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    result = runner.invoke(app, ["run", str(folder), "--out", str(tmp_path / "out"), "--yes"])
    assert result.exit_code == 0, result.output
    assert "Modules" in result.output
    for module in ("M01 Data understanding", "M02 Portfolio and premium", "M05 Profitability"):
        assert module in result.output
    assert "skipped" in result.output and "ran" in result.output
    assert "premium" in result.output and "loaded" in result.output
