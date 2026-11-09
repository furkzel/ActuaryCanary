"""One run at a time, in a worker thread, through the same `pipeline.run` as the command line.

The progress is the stage text the pipeline reports to its `progress` callback, the same text
the terminal prints. A cancel stops the run at the next stage (the callback raises); a stage that
has begun is finished (record 0703). The manager keeps the state of the run in memory only; the
result is read back from the output folder.
"""

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from actuarycanary.canonical.feeds import CanonicalError
from actuarycanary.convert.market import ConversionError
from actuarycanary.methods.assumptions import AssumptionError
from actuarycanary.pipeline import InputError, RunSettings, run
from actuarycanary.recognition.mapping_profiles import ProfileError
from actuarycanary.structures.triangles import TriangleError
from actuarycanary.ui import summary

# the stages of `pipeline.run`, in order, as it reports them (a test compares this list with the
# source of the pipeline, so that a new stage is not forgotten)
STAGES = (
    "Reading and recognising spreadsheets",
    "Checking data against the specifications",
    "Building triangles",
    "Running the reserving methods",
    "Fitting claim sizes and extreme values",
    "Analysing the settlement speed",
    "Computing the reserve ranges and the discounted figures",
    "Rerunning the methods for the sensitivity tables",
    "Flagging anomalies",
    "Computing measures and running modules",
    "Writing the tables",
    "Writing the report",
    "Writing the manifest",
)
WRITING = STAGES[10]  # from here on the run folder and its quality.json exist
# the failures the command line reports as "Cannot run:"
KNOWN_ERRORS = (
    InputError,
    CanonicalError,
    TriangleError,
    ConversionError,
    ProfileError,
    AssumptionError,
)
CACHE_NAME = ".cache"  # inside the output folder (record 0701)

Execute = Callable[..., Any]  # `pipeline.run`, or a stand-in in a test


class RunBusyError(Exception):
    """A run is going; a second one is refused."""


class RunCancelledError(Exception):
    """Raised inside the pipeline's progress callback to stop the run between stages."""


@dataclass(frozen=True)
class RunRequest:
    folder: Path
    out: Path
    profiles: Path
    settings: RunSettings
    kind: str = "run"  # "run" or "demo"
    command: str = ""  # the command line the choices correspond to, shown on the run screen


class RunManager:
    def __init__(self, execute: Execute = run) -> None:
        self._execute = execute
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._request: RunRequest | None = None
        self._state = "idle"
        self._started = 0.0
        self._ended = 0.0
        self._stages: list[tuple[str, float]] = []  # (name, start time)
        self._cancel = threading.Event()
        self._result: tuple[str, Path] | None = None
        self._error: str | None = None
        self._detail: str | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._state == "running"

    def start(self, request: RunRequest) -> None:
        """Start the run in a worker thread; RunBusyError when one is going."""
        with self._lock:
            if self._state == "running":
                raise RunBusyError
            self._request = request
            self._state = "running"
            self._started = time.time()
            self._ended = 0.0
            self._stages = []
            self._cancel.clear()
            self._result = None
            self._error = None
            self._detail = None
            self._thread = threading.Thread(target=self._work, args=(request,), daemon=True)
            self._thread.start()

    def cancel(self) -> bool:
        """Ask the run to stop at the next stage; False when none is going."""
        with self._lock:
            if self._state != "running":
                return False
            self._cancel.set()
            return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _step(self, description: str) -> None:
        if self._cancel.is_set():
            raise RunCancelledError
        with self._lock:
            self._stages.append((description, time.time()))

    def _work(self, request: RunRequest) -> None:
        state, error, detail, result = "done", None, None, None
        try:
            done = self._execute(
                request.folder,
                request.out,
                request.settings,
                cache_dir=request.out / CACHE_NAME,
                progress=self._step,
                profiles_dir=request.profiles,
                confirm=None,
            )
            result = (done.run_id, Path(done.folder))
        except RunCancelledError:
            state = "cancelled"
        except KNOWN_ERRORS as problem:
            state, error = "failed", str(problem)
        except Exception as problem:  # not one of the known failures: say what it was
            state, error = "failed", f"{type(problem).__name__}: {problem}"
            detail = "".join(traceback.format_exception(problem)[-6:])
        with self._lock:
            self._state, self._error, self._detail, self._result = state, error, detail, result
            self._ended = time.time()

    def snapshot(self) -> dict[str, Any]:
        """The state of the run for the page."""
        with self._lock:
            request = self._request
            if request is None:
                return {"state": "idle"}
            now = self._ended or time.time()
            known: list[str] = list(STAGES)
            seen = [name for name, _ in self._stages]
            for name in seen:
                if name not in known:
                    known.append(name)
            stages: list[dict[str, Any]] = []
            for name in known:
                if name not in seen:
                    stages.append({"name": name, "state": "pending", "seconds": None})
                    continue
                index = seen.index(name)
                began = self._stages[index][1]
                if index + 1 < len(seen):
                    ended, outcome = self._stages[index + 1][1], "done"
                else:  # the last stage that began
                    ended = now
                    outcome = {"running": "running", "failed": "failed"}.get(self._state, "done")
                stages.append({"name": name, "state": outcome, "seconds": round(ended - began, 1)})
            running = self._state == "running"
            out = request.out
            started = self._started
            state = self._state
            error, detail = self._error, self._detail
            result = self._result
            cancel_requested = self._cancel.is_set() and running
        if result:
            folder: Path | None = result[1]
        elif WRITING in seen:  # the folder exists once the run id is known
            folder = summary.started_folder(out, started)
        else:
            folder = None
        return {
            "state": state,
            "kind": request.kind,
            "command": request.command,
            "folder": str(request.folder),
            "out": str(out),
            "started": started,
            "elapsed": round(now - started, 1),
            "stages": stages,
            "cancel_requested": cancel_requested,
            "findings": summary.findings_summary(folder) if folder else None,
            "run_id": result[0] if result else None,
            "run_folder": str(result[1]) if result else None,
            "error": error,
            "detail": detail,
            "partial": str(folder) if folder and state in ("failed", "cancelled") else None,
        }
