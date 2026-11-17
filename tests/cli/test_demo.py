import hashlib
import json
import sys
import tomllib
import webbrowser
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

import actuarycanary.cli as cli
from actuarycanary import __version__
from actuarycanary.cli.demo import find_demo_folder, place_demo_profiles, program_root
from actuarycanary.ledger.resolve import profile_in_use
from actuarycanary.manifest.metadata import load_metadata

ROOT = Path(__file__).parents[2]
runner = CliRunner()


def test_the_version_is_the_same_in_project_yaml_the_package_and_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert load_metadata().version == __version__ == pyproject["project"]["version"]


def test_the_demo_folder_is_found_next_to_the_program() -> None:
    folder = find_demo_folder()
    assert (folder / "claim_valuations.xlsx").is_file()
    assert folder.parent.name == "examples"


def test_the_demo_folder_is_found_from_a_bundle_without_the_repository(tmp_path: Path) -> None:
    example = tmp_path / "examples" / "demo"
    example.mkdir(parents=True)
    (example / "claim_valuations.xlsx").touch()
    inside = tmp_path / "_internal" / "actuarycanary" / "cli"
    inside.mkdir(parents=True)
    assert find_demo_folder(inside / "demo.pyc") == example


def test_a_frozen_program_finds_the_demo_and_its_profile_where_the_bundle_unpacks_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PyInstaller sets `sys.frozen` and `sys._MEIPASS`; the spec puts the workbooks and the
    confirmed profile at examples/demo and examples/demo/report there (record 0816). The layout
    is simulated; the program itself cannot be built here."""
    unpacked = tmp_path / "_internal"
    demo = unpacked / "examples" / "demo"
    (demo / "report").mkdir(parents=True)
    (demo / "claim_valuations.xlsx").touch()
    shipped = next((find_demo_folder() / "report").glob("ledger-*.yaml"))
    (demo / "report" / shipped.name).write_bytes(shipped.read_bytes())
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(unpacked), raising=False)
    monkeypatch.chdir(tmp_path / "elsewhere")  # no repository around the program
    assert program_root() == unpacked
    folder = find_demo_folder()
    assert folder == demo.resolve()
    (placed,) = place_demo_profiles(folder, tmp_path / "profiles")
    assert placed.read_bytes() == shipped.read_bytes()


def test_the_source_tree_starts_the_lookup_at_the_module_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert program_root().name == "demo.py"
    assert program_root(Path("x")) == Path("x")


def test_demo_says_so_when_the_example_data_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing() -> Path:
        raise FileNotFoundError("examples/demo not found")

    monkeypatch.setattr(cli, "find_demo_folder", missing)
    result = runner.invoke(cli.app, ["demo", "--no-open"])
    assert result.exit_code == 1
    assert "examples/demo not found" in result.output


def test_the_demo_runs_on_its_shipped_confirmed_ledger_profile(tmp_path: Path) -> None:
    ledger = pl.read_excel(find_demo_folder() / "ledger.xlsx", engine="calamine")
    assert not profile_in_use(ledger, tmp_path / "none").profile.confirmed  # a proposal
    placed = place_demo_profiles(find_demo_folder(), tmp_path / "profiles")
    shipped = find_demo_folder() / "report" / placed[0].name
    assert len(placed) == 1 and placed[0].read_bytes() == shipped.read_bytes()
    used = profile_in_use(ledger, tmp_path / "profiles")
    assert used.saved and used.profile.confirmed and used.path == placed[0]
    assert used.sha256 == hashlib.sha256(shipped.read_bytes()).hexdigest()


def test_a_profile_already_in_the_folder_is_kept_and_other_data_still_gets_a_proposal(
    tmp_path: Path,
) -> None:
    placed = place_demo_profiles(find_demo_folder(), tmp_path)
    placed[0].write_text("the person's own", encoding="utf-8")
    assert place_demo_profiles(find_demo_folder(), tmp_path) == []
    assert placed[0].read_text(encoding="utf-8") == "the person's own"
    assert place_demo_profiles(tmp_path / "no_demo", tmp_path / "empty") == []
    assert not (tmp_path / "empty").exists()
    # a chart of accounts that is not the demo's finds no saved profile there: proposed, saved
    other = pl.DataFrame({"entity": ["E"], "account": ["601"], "account_name": ["Primler"]})
    mine = profile_in_use(other, tmp_path)
    assert not mine.saved and not mine.profile.confirmed and mine.path is not None
    assert mine.path.is_file() and mine.path != placed[0]


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("opens", [True, False])
def test_demo_runs_on_the_example_and_opens_the_report_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opens: bool
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.chdir(tmp_path)
    flag = "--open" if opens else "--no-open"
    result = runner.invoke(cli.app, ["demo", "--out", str(tmp_path / "out"), flag])
    assert result.exit_code == 0, result.output
    report = next((tmp_path / "out").glob("*/report.html"))
    assert opened == ([report.resolve().as_uri()] if opens else [])
    assert "canary run <folder>" in result.output
    assert report.parent.name in result.output


@pytest.mark.slow
@pytest.mark.integration
def test_demo_equals_a_run_on_the_same_folder_by_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    demo = runner.invoke(cli.app, ["demo", "--out", str(tmp_path / "demo"), "--no-open"])
    assert demo.exit_code == 0, demo.output
    run = runner.invoke(
        cli.app,
        [
            "run",
            str(find_demo_folder()),
            "--yes",
            "--curve",
            "TRY_GOV",
            "--out",
            str(tmp_path / "run"),
        ],
    )
    assert run.exit_code == 0, run.output
    first, second = (next((tmp_path / name).glob("*/manifest.json")) for name in ("demo", "run"))
    # the demo placed its confirmed ledger profile in ./profiles and the run read it there
    # (record 0812): both give the run id of the committed demo, which names the folder
    committed = json.loads((find_demo_folder() / "report" / "manifest.json").read_bytes())
    assert first.parent.name == second.parent.name == committed["run_id"]
    assert first.read_bytes() == second.read_bytes()
    for name in ("reinsurance_reconciliation.csv", "measures.csv"):
        assert (first.parent / name).read_bytes() == (second.parent / name).read_bytes(), name
