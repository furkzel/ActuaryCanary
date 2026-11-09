"""The local server of `canary ui`: standard library only, bound to 127.0.0.1, token on every call.

Every request must carry the random token of this start (in the query or in the header
`X-Canary-Token`) and a Host header naming this address; the page, its two static files, the
report of a finished run and the JSON interface are the only routes (record 0700). The server
reads the folders the person points it to and writes only what the pipeline and the mapping save
write (record 0701); it deletes nothing.
"""

import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from actuarycanary import __version__
from actuarycanary.cli.demo import DEMO_CURVE, find_demo_folder
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.io.excel import spreadsheets
from actuarycanary.pipeline import RunSettings
from actuarycanary.report.render import REPORT_NAME
from actuarycanary.ui import folders, scan, settings, strings, summary
from actuarycanary.ui.runner import CACHE_NAME, STAGES, RunBusyError, RunManager, RunRequest

UI_DIR = Path(__file__).parent
TEMPLATE_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"
STATIC_TYPES = {"app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}
MAX_BODY = 1_000_000
TOKEN_HEADER = "X-Canary-Token"

Opener = Callable[[Path], None]


def open_folder(path: Path) -> None:
    """Show a folder in the file manager of the system."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


class UiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        port: int = 0,
        default_out: str = settings.DEFAULT_OUT,
        default_profiles: str = settings.DEFAULT_PROFILES,
        manager: RunManager | None = None,
        opener: Opener = open_folder,
    ) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(18)
        self.manager = manager or RunManager()
        self.default_out = default_out
        self.default_profiles = default_profiles
        self.opener = opener
        self.demo_out: Path | None = None
        self._environment = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "j2"]),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def url(self, language: str = "en") -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}&lang={language}"

    def render_page(self, language: str) -> str:
        table = strings.table(language)
        return self._environment.get_template("index.html.j2").render(
            s=lambda key, **values: strings.fill(table[key], values),
            lang=language,
            version=__version__,
            token=self.token,
            strings_json=json.dumps(table, ensure_ascii=False).replace("</", "<\\/"),
            stages_json=json.dumps(list(STAGES)),
            options=settings_options(),
        )

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):  # a tab closed in the middle of a reply
            return
        super().handle_error(request, client_address)

    def resolve(self, text: str, default: str) -> Path:
        """A folder the person named; a relative path starts at the working folder."""
        path = Path(text.strip() or default).expanduser()
        path = (Path.cwd() / path) if not path.is_absolute() else path
        if path.exists() and not path.is_dir():
            raise ApiError(HTTPStatus.BAD_REQUEST, "out_invalid", str(path))
        return path

    def demo_folder(self) -> Path:
        if self.demo_out is None:
            self.demo_out = Path(tempfile.mkdtemp(prefix="canary-demo-"))
        return self.demo_out


def settings_options() -> dict[str, tuple[str, ...]]:
    return {
        "basis": settings.BASES,
        "value": settings.VALUES,
        "origin_axis": settings.ORIGIN_AXES,
        "period": settings.PERIODS,
        "currency_view": settings.CURRENCY_VIEWS,
    }


class Handler(BaseHTTPRequestHandler):
    server: UiServer
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # nothing is printed or sent anywhere
        return

    # --- plumbing -----------------------------------------------------------------------

    def _query(self) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _allowed(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.port
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        sent = self.headers.get(TOKEN_HEADER) or self._query().get("t", "")
        return hmac.compare_digest(sent.encode(), self.server.token.encode())

    def _send(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "bad_request")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", str(error)) from error
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request")
        return data

    def _dispatch(self, method: str) -> None:
        if not self._allowed():
            self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain; charset=utf-8")
            return
        path = urlsplit(self.path).path
        try:
            if method == "GET" and path == "/":
                language = self._query().get("lang", "en")
                page = self.server.render_page(language if language in strings.LANGUAGES else "en")
                self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")
            elif method == "GET" and path.startswith("/static/"):
                self._static(path.removeprefix("/static/"))
            elif method == "GET" and path == "/report":
                self._report()
            elif path.startswith("/api/"):
                handler = getattr(self, f"{method.lower()}_{path.removeprefix('/api/')}", None)
                if handler is None or not path.removeprefix("/api/").isidentifier():
                    raise ApiError(HTTPStatus.NOT_FOUND, "not_found")
                self._json(handler())
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "not_found")
        except ApiError as error:
            self._json({"error": {"code": error.code, "detail": error.detail}}, error.status)
        except scan.ScanError as error:
            self._json(
                {"error": {"code": error.code, "detail": error.detail}}, HTTPStatus.BAD_REQUEST
            )

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    # --- files --------------------------------------------------------------------------

    def _static(self, name: str) -> None:
        kind = STATIC_TYPES.get(name)
        if kind is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "not_found")
        self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), kind)

    def _report(self) -> None:
        query = self._query()
        out = self.server.resolve(query.get("out", ""), self.server.default_out)
        try:
            folder = summary.run_folder(out, query.get("run", ""))
        except summary.RunNotFoundError as error:
            raise ApiError(HTTPStatus.NOT_FOUND, "run_not_found", query.get("run", "")) from error
        report = folder / REPORT_NAME
        if not report.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "report_missing", str(report))
        self._send(HTTPStatus.OK, report.read_bytes(), "text/html; charset=utf-8")

    # --- JSON interface: GET -------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        server = self.server
        return {
            "version": __version__,
            "cwd": str(Path.cwd()),
            "out": str(server.resolve(server.default_out, settings.DEFAULT_OUT)),
            "profiles": str(server.resolve(server.default_profiles, settings.DEFAULT_PROFILES)),
            "run": server.manager.snapshot(),
        }

    def get_browse(self) -> dict[str, Any]:
        try:
            return folders.browse(self._query().get("path"))
        except FileNotFoundError as error:
            raise ApiError(HTTPStatus.NOT_FOUND, "folder_missing", str(error)) from error
        except PermissionError as error:
            raise ApiError(HTTPStatus.FORBIDDEN, "folder_denied", str(error)) from error

    def get_run(self) -> dict[str, Any]:
        return self.server.manager.snapshot()

    def get_runs(self) -> dict[str, Any]:
        out = self.server.resolve(self._query().get("out", ""), self.server.default_out)
        return {"out": str(out), "runs": summary.past_runs(out)}

    def get_result(self) -> dict[str, Any]:
        query = self._query()
        out = self.server.resolve(query.get("out", ""), self.server.default_out)
        try:
            return summary.summarise_run(summary.run_folder(out, query.get("run", "")))
        except summary.RunNotFoundError as error:
            raise ApiError(HTTPStatus.NOT_FOUND, "run_not_found", query.get("run", "")) from error

    # --- JSON interface: POST ------------------------------------------------------------

    def _form(self, body: dict[str, Any]) -> settings.Form:
        form = body.get("form")
        return settings.form_from_json(form if isinstance(form, dict) else {})

    def _paths(self, form: settings.Form) -> tuple[Path, Path, Path]:
        server = self.server
        folder = scan.folder_of(form.folder)
        out = server.resolve(form.out, server.default_out)
        profiles = server.resolve(form.profiles, server.default_profiles)
        return folder, out, profiles

    def _command_form(self, form: settings.Form) -> settings.Form:
        """The form with the folders written as the command line needs them: left out when they
        are the defaults of `canary run` (out, profiles in the working folder)."""
        server = self.server
        shown: dict[str, str] = {}
        for key, text, default_text, default in (
            ("out", form.out, server.default_out, settings.DEFAULT_OUT),
            ("profiles", form.profiles, server.default_profiles, settings.DEFAULT_PROFILES),
        ):
            path = server.resolve(text, default_text)
            shown[key] = "" if path == server.resolve("", default) else str(path)
        return replace(form, **shown)

    def post_command(self) -> dict[str, Any]:
        body = self._body()
        form = self._form(body)
        command = settings.command_line(self._command_form(form), bool(body.get("pending")))
        return {"command": command}

    def post_scan(self) -> dict[str, Any]:
        form = self._form(self._body())
        folder, out, profiles = self._paths(form)
        if not spreadsheets(folder):
            raise ApiError(HTTPStatus.BAD_REQUEST, "no_spreadsheets", str(folder))
        d = scan.dictionary()
        scans = scan.scan_folder(folder, d, out / CACHE_NAME, profiles)
        return scan.scan_json(scans, d, folder) | {"profiles": str(profiles)}

    def post_sheet(self) -> dict[str, Any]:
        body = self._body()
        form = self._form(body)
        folder, out, profiles = self._paths(form)
        concept = body.get("concept") or None
        d = scan.dictionary()
        return scan.sheet_after_concept(
            folder,
            d,
            out / CACHE_NAME,
            profiles,
            str(body.get("file", "")),
            str(body.get("sheet", "")),
            concept,
        )

    def post_mapping(self) -> dict[str, Any]:
        body = self._body()
        form = self._form(body)
        folder, out, profiles = self._paths(form)
        choices = body.get("sheets")
        if not isinstance(choices, list):
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request")
        d = scan.dictionary()
        written = scan.save_choices(folder, d, out / CACHE_NAME, profiles, choices)
        scans = scan.scan_folder(folder, d, out / CACHE_NAME, profiles)
        return scan.scan_json(scans, d, folder) | {
            "profiles": str(profiles),
            "saved": [str(p) for p in written],
        }

    def post_start(self) -> dict[str, Any]:
        body = self._body()
        form = self._form(body)
        folder, out, profiles = self._paths(form)
        if not spreadsheets(folder):
            raise ApiError(HTTPStatus.BAD_REQUEST, "no_spreadsheets", str(folder))
        try:
            run_settings = settings.build_run_settings(form)
        except settings.SettingsRejectedError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "settings_rejected", str(error)) from error
        request = RunRequest(
            folder,
            out,
            profiles,
            run_settings,
            "run",
            settings.command_line(self._command_form(form), bool(body.get("pending"))),
        )
        return self._start(request)

    def post_demo(self) -> dict[str, Any]:
        body = self._body()
        language = str(body.get("lang", "en"))
        if language not in strings.LANGUAGES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request")
        try:
            folder = find_demo_folder()
        except FileNotFoundError as error:
            raise ApiError(HTTPStatus.NOT_FOUND, "demo_missing", str(error)) from error
        out = self.server.demo_folder()
        form = settings.Form(
            folder=str(folder), out=str(out), values={"lang": language, "curve": DEMO_CURVE}
        )
        run_settings = RunSettings(
            language=language, discount=DiscountSettings(curve_id=DEMO_CURVE)
        )
        profiles = self.server.resolve("", self.server.default_profiles)
        request = RunRequest(
            folder, out, profiles, run_settings, "demo", settings.command_line(form, True)
        )
        return self._start(request)

    def _start(self, request: RunRequest) -> dict[str, Any]:
        try:
            self.server.manager.start(request)
        except RunBusyError as error:
            raise ApiError(HTTPStatus.CONFLICT, "run_busy") from error
        return {"started": True, "out": str(request.out)}

    def post_cancel(self) -> dict[str, Any]:
        self._body()
        return {"cancel_requested": self.server.manager.cancel()}

    def post_open(self) -> dict[str, Any]:
        body = self._body()
        out = self.server.resolve(str(body.get("out", "")), self.server.default_out)
        try:
            folder = summary.run_folder(out, str(body.get("run", "")))
        except summary.RunNotFoundError as error:
            raise ApiError(
                HTTPStatus.NOT_FOUND, "run_not_found", str(body.get("run", ""))
            ) from error
        try:
            self.server.opener(folder)
        except OSError as error:
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "open_failed", str(error)) from error
        return {"opened": str(folder)}

    def post_quit(self) -> dict[str, Any]:
        body = self._body()
        if self.server.manager.active and not body.get("force"):
            raise ApiError(HTTPStatus.CONFLICT, "run_active")
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        return {"quitting": True}
