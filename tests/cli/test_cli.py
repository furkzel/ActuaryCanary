import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from actuarycanary import __version__
from actuarycanary.cli import app, main
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


def _cp1252_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", write_through=True)


def test_the_command_group_switches_the_console_streams_to_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, err = _cp1252_stream(), _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    main(version=False)
    for stream in (out, err):
        assert stream.encoding == "utf-8"
        stream.write("ultimate ÷ truth → ≥ 0.75")  # not in cp1252: would raise before
        assert stream.buffer.getvalue().decode("utf-8") == "ultimate ÷ truth → ≥ 0.75"  # type: ignore[attr-defined]


@pytest.mark.slow  # starts a Python process that imports the whole package
def test_output_redirected_to_a_file_is_utf8_under_a_legacy_code_page(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    code = "from actuarycanary.cli import main; main(version=False); print('ultimate ÷ truth → ≥')"
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    with target.open("wb") as handle:
        done = subprocess.run(
            [sys.executable, "-c", code], stdout=handle, stderr=subprocess.PIPE, env=env
        )
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert target.read_bytes().decode("utf-8").strip() == "ultimate ÷ truth → ≥"


BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"


@pytest.mark.integration
def test_run_writes_report_and_manifest(cli_run: tuple[Path, str]) -> None:
    folder, output = cli_run
    assert "Run id" in output
    # one line counts the method diagnostics per line of business, wrapped for 80 columns
    start = output.index("Method diagnostics:")
    block = output[start : output.index("data rules touched")].splitlines()
    assert "MOTOR_TPL" in " ".join(block) and all(len(line) <= 80 for line in block)
    assert (folder / "report.html").exists() and (folder / "manifest.json").exists()


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


@pytest.mark.slow
@pytest.mark.integration
def test_new_layouts_without_answers_or_yes_stop_with_a_message(tmp_path: Path) -> None:
    arguments = ["run", str(MESSY), "--out", str(tmp_path / "out")]
    result = runner.invoke(app, [*arguments, "--profiles", str(tmp_path / "profiles")])
    assert result.exit_code == 1
    assert "--yes" in result.output
    assert not (tmp_path / "profiles").exists()


@pytest.mark.integration
@pytest.mark.slow
def test_yes_uses_the_proposals_without_saving_or_asking(tmp_path: Path) -> None:
    arguments = ["run", str(MESSY), "--out", str(tmp_path / "out"), "--yes"]
    result = runner.invoke(app, [*arguments, "--profiles", str(tmp_path / "profiles")])
    assert result.exit_code == 0, result.output
    assert "Accept, edit or skip" not in result.output
    assert "automatic" in result.output
    assert not (tmp_path / "profiles").exists()


@pytest.mark.integration
@pytest.mark.slow
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
@pytest.mark.slow
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


def test_assumptions_file_without_a_reason_is_rejected_before_the_run(tmp_path: Path) -> None:
    register = tmp_path / "register.yaml"
    register.write_text(
        "entries:\n  - {method: MT02, name: tail_factor, value: 1.1, who: reviewer}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["run", str(tmp_path), "--assumptions", str(register)])
    assert result.exit_code == 2
    assert "needs a reason" in result.output
    absent = tmp_path / "none.yaml"
    missing = runner.invoke(app, ["run", str(tmp_path), "--assumptions", str(absent)])
    assert missing.exit_code == 2 and "Settings rejected" in missing.output


@pytest.mark.integration
@pytest.mark.slow
def test_assumptions_file_reaches_the_run_and_a_wrong_target_stops_it(tmp_path: Path) -> None:
    register = tmp_path / "register.yaml"
    register.write_text(
        "entries:\n"
        "  - {method: MT02, name: tail_factor, value: 1.1, who: reviewer, when: 2026-01-05,"
        " why: long tail}\n",
        encoding="utf-8",
    )
    arguments = ["run", str(BASELINE), "--out", str(tmp_path / "out"), "--yes"]
    result = runner.invoke(app, [*arguments, "--assumptions", str(register)])
    assert result.exit_code == 0, result.output
    (assumptions,) = (tmp_path / "out").glob("*/assumptions.csv")
    assert "reviewer" in assumptions.read_text(encoding="utf-8")
    register.write_text(
        "entries:\n"
        "  - {method: MT02, name: exclusion, target: '2024:99-100', value: true, who: r, why: x}\n",
        encoding="utf-8",
    )
    wrong = runner.invoke(app, [*arguments, "--assumptions", str(register)])
    assert wrong.exit_code == 1 and "not a link ratio of this triangle" in wrong.output
