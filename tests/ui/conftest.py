import http.client
import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from actuarycanary.ui.runner import STAGES, RunManager
from actuarycanary.ui.server import UiServer


class Client:
    """A client of one running server that can send the token, a wrong one, or none."""

    def __init__(self, server: UiServer) -> None:
        self.server = server

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = "ok",
        host: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=30)
        sent = {"Host": host or f"127.0.0.1:{self.server.port}", **(headers or {})}
        if token == "ok":
            token = self.server.token
        if token is not None:
            sent["X-Canary-Token"] = token
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            sent["Content-Type"] = "application/json"
        connection.request(method, path, body=data, headers=sent)
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, dict(response.getheaders()), payload)
        connection.close()
        return result

    def get(self, path: str, **kw: Any) -> tuple[int, dict[str, str], bytes]:
        return self.request("GET", path, **kw)

    def get_json(self, path: str) -> tuple[int, dict[str, Any]]:
        status, _, payload = self.request("GET", path)
        return status, json.loads(payload)

    def post(self, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        status, _, payload = self.request("POST", path, {} if body is None else body)
        return status, json.loads(payload)


@pytest.fixture
def opened() -> list[Path]:
    return []


@pytest.fixture
def calls() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def make_server(
    tmp_path: Path, opened: list[Path], calls: list[dict[str, Any]]
) -> Iterator[Callable[..., Client]]:
    """Servers on a random port with a stand-in for the pipeline; all stopped at the end."""
    started: list[UiServer] = []

    def build(execute: Callable[..., Any] | None = None, **kw: Any) -> Client:
        def recording(folder: Path, out: Path, settings: Any, **options: Any) -> Any:
            calls.append({"folder": folder, "out": out, "settings": settings, **options})
            if execute is None:
                raise RuntimeError("no stand-in for the pipeline given")
            return execute(folder, out, settings, **options)

        server = UiServer(
            0,
            kw.pop("default_out", str(tmp_path / "out")),
            kw.pop("default_profiles", str(tmp_path / "profiles")),
            manager=RunManager(recording),
            opener=opened.append,
        )
        threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True).start()
        started.append(server)
        return Client(server)

    yield build
    for server in started:
        server.shutdown()
        server.server_close()


def stages_then(result: Any) -> Callable[..., Any]:
    """A stand-in for `pipeline.run`: reports every stage, then returns `result`."""

    def execute(folder: Path, out: Path, settings: Any, **options: Any) -> Any:
        for stage in STAGES:
            options["progress"](stage)
        return result

    return execute


ROOT = Path(__file__).parents[2]
MESSY = ROOT / "examples" / "messy_headers"
BASELINE_TINY = ROOT / "tests" / "fixtures" / "synthetic" / "baseline"


@pytest.fixture(scope="session")
def messy_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An output folder shared by the tests that read the messy example and the tiny baseline;
    their spreadsheets are parsed once, here, into the reader cache that lives in it."""
    from actuarycanary.ui import scan
    from actuarycanary.ui.runner import CACHE_NAME

    out = tmp_path_factory.mktemp("messy_out")
    d = scan.dictionary()
    for folder in (MESSY, BASELINE_TINY):
        scan.scan_folder(folder, d, out / CACHE_NAME, None)
    return out


@pytest.fixture(scope="session")
def messy_one(tmp_path_factory: pytest.TempPathFactory, messy_out: Path) -> Path:
    """A folder with one messy workbook (claim_valuations), small enough to scan in a test."""
    import shutil

    folder = tmp_path_factory.mktemp("messy_one")
    shutil.copy(MESSY / "claim_valuations.xlsx", folder)
    return folder
