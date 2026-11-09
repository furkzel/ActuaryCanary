"""One run at a time, cancelled between stages, failures shown as the terminal shows them
(record 0703)."""

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from actuarycanary.canonical.feeds import CanonicalError
from actuarycanary.pipeline import InputError, RunSettings
from actuarycanary.ui.runner import (
    CACHE_NAME,
    STAGES,
    WRITING,
    RunBusyError,
    RunManager,
    RunRequest,
)


def request(tmp_path: Path, **kw: Any) -> RunRequest:
    return RunRequest(
        folder=tmp_path / "in",
        out=tmp_path / "out",
        profiles=tmp_path / "profiles",
        settings=RunSettings(),
        **kw,
    )


class Result:
    run_id = "0123456789abcdef"
    folder = Path("unused")


def test_a_run_reports_every_stage_and_the_result(tmp_path: Path) -> None:
    def execute(folder, out, settings, **options):
        for stage in STAGES:
            options["progress"](stage)
        return Result()

    manager = RunManager(execute)
    manager.start(request(tmp_path, command="canary run x"))
    manager.wait(10)
    shown = manager.snapshot()
    assert shown["state"] == "done" and shown["run_id"] == Result.run_id
    assert [s["name"] for s in shown["stages"]] == list(STAGES)
    assert {s["state"] for s in shown["stages"]} == {"done"}
    assert shown["command"] == "canary run x" and shown["elapsed"] >= 0
    assert shown["error"] is None and shown["partial"] is None


def test_the_pipeline_is_called_as_the_command_line_calls_it(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def execute(folder, out, settings, **options):
        seen.update(folder=folder, out=out, settings=settings, **options)
        return Result()

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    manager.wait(10)
    assert seen["folder"] == tmp_path / "in" and seen["out"] == tmp_path / "out"
    assert seen["settings"] == RunSettings()
    assert seen["profiles_dir"] == tmp_path / "profiles"
    assert seen["cache_dir"] == tmp_path / "out" / CACHE_NAME  # inside the output folder
    assert seen["confirm"] is None and callable(seen["progress"])


def test_a_second_run_while_one_is_going_is_refused(tmp_path: Path) -> None:
    release = threading.Event()

    def execute(folder, out, settings, **options):
        options["progress"](STAGES[0])
        release.wait(10)
        return Result()

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    assert manager.active
    with pytest.raises(RunBusyError):
        manager.start(request(tmp_path))
    release.set()
    manager.wait(10)
    assert not manager.active
    manager.start(request(tmp_path))  # a finished run does not block the next
    manager.wait(10)


def test_cancel_stops_the_run_at_the_next_stage(tmp_path: Path) -> None:
    gate = threading.Event()
    reached: list[str] = []

    def execute(folder, out, settings, **options):
        for stage in STAGES:
            options["progress"](stage)
            reached.append(stage)
            gate.wait(10)
        return Result()

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    while not reached:
        time.sleep(0.01)
    assert manager.cancel() is True
    assert manager.snapshot()["cancel_requested"] is True
    gate.set()
    manager.wait(10)
    shown = manager.snapshot()
    assert shown["state"] == "cancelled" and reached == [STAGES[0]]  # the begun stage was finished
    assert shown["run_id"] is None and shown["error"] is None
    assert manager.cancel() is False  # nothing is going


def test_a_known_failure_shows_the_message_the_terminal_shows(tmp_path: Path) -> None:
    def execute(folder, out, settings, **options):
        options["progress"](STAGES[0])
        raise InputError("C:/data: no sheet was recognised as claim_valuations")

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    manager.wait(10)
    shown = manager.snapshot()
    assert shown["state"] == "failed"
    assert shown["error"] == "C:/data: no sheet was recognised as claim_valuations"
    assert shown["detail"] is None
    assert [s["state"] for s in shown["stages"]][:2] == ["failed", "pending"]


def test_an_unexpected_failure_names_its_kind_and_keeps_the_trace(tmp_path: Path) -> None:
    def execute(folder, out, settings, **options):
        raise ZeroDivisionError("division by zero")

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    manager.wait(10)
    shown = manager.snapshot()
    assert shown["state"] == "failed" and shown["error"] == "ZeroDivisionError: division by zero"
    assert "ZeroDivisionError" in shown["detail"]


def test_a_failure_after_the_folder_exists_names_the_partial_output(tmp_path: Path) -> None:
    def execute(folder, out, settings, **options):
        for stage in STAGES[: STAGES.index(WRITING) + 1]:
            options["progress"](stage)
        folder = out / "0123456789abcdef"
        folder.mkdir(parents=True)
        (folder / "quality.json").write_text(json.dumps({"findings": []}), encoding="utf-8")
        raise CanonicalError("claim_valuations: a required column is empty")

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    manager.wait(10)
    shown = manager.snapshot()
    assert shown["state"] == "failed" and "required column" in shown["error"]
    assert shown["partial"] == str(tmp_path / "out" / "0123456789abcdef")
    assert shown["findings"]["counts"] == {"BLOCKING": 0, "WARNING": 0, "INFO": 0}


def test_the_findings_appear_while_the_run_goes_on(tmp_path: Path) -> None:
    gate = threading.Event()
    written = threading.Event()

    def execute(folder, out, settings, **options):
        for stage in STAGES[: STAGES.index(WRITING) + 1]:
            options["progress"](stage)
        folder = out / "0123456789abcdef"
        folder.mkdir(parents=True)
        quality = {"findings": [{"severity": "WARNING", "rule": "DV-X", "count": 2, "checked": 9}]}
        (folder / "quality.json").write_text(json.dumps(quality), encoding="utf-8")
        written.set()
        gate.wait(10)
        return Result()

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    assert written.wait(10)
    shown = manager.snapshot()
    assert shown["state"] == "running" and shown["findings"]["counts"]["WARNING"] == 1
    assert shown["partial"] is None  # not an error while it runs
    gate.set()
    manager.wait(10)


def test_an_old_quality_file_is_not_this_runs_finding(tmp_path: Path) -> None:
    old = tmp_path / "out" / "ffffffffffffffff"
    old.mkdir(parents=True)
    (old / "quality.json").write_text(json.dumps({"findings": []}), encoding="utf-8")
    time.sleep(0.05)
    gate = threading.Event()
    reached = threading.Event()

    def execute(folder, out, settings, **options):
        for stage in STAGES[: STAGES.index(WRITING) + 1]:
            options["progress"](stage)
        reached.set()
        gate.wait(10)
        return Result()

    manager = RunManager(execute)
    manager.start(request(tmp_path))
    assert reached.wait(10)
    assert manager.snapshot()["findings"] is None
    gate.set()
    manager.wait(10)


def test_an_idle_manager_says_so() -> None:
    assert RunManager().snapshot() == {"state": "idle"}
