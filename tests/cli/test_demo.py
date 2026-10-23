import tomllib
import webbrowser
from pathlib import Path

import pytest
from typer.testing import CliRunner

import actuarycanary.cli as cli
from actuarycanary import __version__
from actuarycanary.cli.demo import find_demo_folder
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
    example = tmp_path / "examples" / "baseline"
    example.mkdir(parents=True)
    (example / "claim_valuations.xlsx").touch()
    inside = tmp_path / "_internal" / "actuarycanary" / "cli"
    inside.mkdir(parents=True)
    assert find_demo_folder(inside / "demo.pyc") == example


def test_demo_says_so_when_the_example_data_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing() -> Path:
        raise FileNotFoundError("examples/demo not found")

    monkeypatch.setattr(cli, "find_demo_folder", missing)
    result = runner.invoke(cli.app, ["demo", "--no-open"])
    assert result.exit_code == 1
    assert "examples/demo not found" in result.output


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


@pytest.mark.slow
@pytest.mark.integration
def test_demo_equals_a_run_on_the_same_folder_by_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    demo = runner.invoke(cli.app, ["demo", "--out", str(tmp_path / "demo"), "--no-open"])
    assert demo.exit_code == 0, demo.output
    run = runner.invoke(
        cli.app, ["run", str(find_demo_folder()), "--yes", "--out", str(tmp_path / "run")]
    )
    assert run.exit_code == 0, run.output
    first, second = (next((tmp_path / name).glob("*/manifest.json")) for name in ("demo", "run"))
    assert first.parent.name == second.parent.name  # the run id names the folder
    assert first.read_bytes() == second.read_bytes()
