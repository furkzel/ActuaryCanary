"""Real runs through the interface: the same run id and files as the command line, a saved
mapping used by the next run, the demo, and nothing written outside the output folder
(records 0701, 0702, 0706). Each runs the whole pipeline, so each is marked slow."""

import json
from pathlib import Path

import pytest

from actuarycanary.ui import scan
from actuarycanary.ui.runner import CACHE_NAME, RunManager, RunRequest
from actuarycanary.ui.settings import Form, build_run_settings

from .conftest import BASELINE_TINY, MESSY, Client

pytestmark = pytest.mark.slow


def tree(root: Path) -> dict[str, int]:
    return {str(p.relative_to(root)): p.stat().st_size for p in root.rglob("*") if p.is_file()}


def outputs(folder: Path) -> dict[str, str]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    return {o["name"]: o["sha256"] for o in manifest["outputs"]}


def run_through_the_interface(folder: Path, out: Path, profiles: Path, **values: str) -> Path:
    form = Form(folder=str(folder), out=str(out), profiles=str(profiles), values=values)
    manager = RunManager()
    manager.start(RunRequest(folder, out, profiles, build_run_settings(form)))
    manager.wait(600)
    shown = manager.snapshot()
    assert shown["state"] == "done", (shown["error"], shown["detail"])
    return Path(shown["run_folder"])


def test_the_same_run_id_and_files_as_the_command_line_and_nothing_written_elsewhere(
    tmp_path: Path, default_run, cli_run: tuple[Path, str]
) -> None:
    sandbox = tmp_path / "sandbox"
    out = sandbox / "out"
    inputs_before = tree(BASELINE_TINY)
    folder = run_through_the_interface(BASELINE_TINY, out, out / "profiles")
    assert folder.name == default_run.run_id == cli_run[0].name
    assert outputs(folder) == outputs(default_run.folder) == outputs(cli_run[0])
    assert (folder / "report.html").read_bytes() == (
        default_run.folder / "report.html"
    ).read_bytes()
    # the sandbox holds the output folder and nothing else; the inputs are as they were
    assert [p.name for p in sandbox.iterdir()] == ["out"]
    assert sorted(p.name for p in out.iterdir()) == sorted([folder.name, CACHE_NAME])
    assert tree(BASELINE_TINY) == inputs_before


def test_the_report_language_changes_the_run_id_as_on_the_command_line(tmp_path: Path) -> None:
    folder = run_through_the_interface(BASELINE_TINY, tmp_path / "out", tmp_path / "p", lang="tr")
    assert folder.name == "90b1f5cf4acec843"  # the Turkish report of the tiny baseline (1.2.0)
    assert 'lang="tr"' in (folder / "report.html").read_text(encoding="utf-8")[:400]


def test_a_second_run_uses_the_mapping_saved_by_the_first_edit(tmp_path: Path) -> None:
    out, profiles = tmp_path / "out", tmp_path / "profiles"
    d = scan.dictionary()
    cache = out / CACHE_NAME
    item = next(
        s
        for f in scan.scan_folder(MESSY, d, cache, None)
        for s in f.sheets
        if s.recognition.sheet == "Hasar"
    )
    columns = {m.source: (m.field if m.used else None) for m in item.recognition.mappings}
    columns["RUCU TAHSILAT "] = None
    choice = {"file": "claim_valuations.xlsx", "sheet": "Hasar", "concept": "claim_valuations",
              "amounts": "to_date", "columns": columns}  # fmt: skip
    scan.save_choices(MESSY, d, cache, profiles, [choice])
    folder = run_through_the_interface(MESSY, out, profiles)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    used = {m["sheet"]: m for m in manifest["mapping_profiles"]}
    assert used["Hasar"]["source"] == "saved" and used["Hasar"]["profile_sha256"]
    assert "subrogation_to_date" not in [c[1] for c in used["Hasar"]["columns"]]
    assert used["Hasar Listesi"]["source"] == "automatic"  # not confirmed, so used as proposed


def test_the_demo_through_the_interface_has_the_run_id_of_the_demo(
    make_server, tmp_path: Path
) -> None:
    from actuarycanary.pipeline import run

    client: Client = make_server(run)
    status, answer = client.post("/api/demo", {"lang": "en"})
    assert status == 200
    client.server.manager.wait(900)
    shown = client.get_json("/api/run")[1]
    assert shown["state"] == "done", (shown["error"], shown["detail"])
    committed = json.loads(
        (Path(__file__).parents[2] / "examples" / "demo" / "report" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert shown["run_id"] == committed["run_id"]
    assert Path(shown["run_folder"]).parent == Path(answer["out"])
    status, _, page = client.get(f"/report?out={answer['out']}&run={shown['run_id']}")
    assert status == 200 and page.startswith(b"<!doctype html>")
