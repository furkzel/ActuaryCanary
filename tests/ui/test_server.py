"""The server in-process on a random port: the token, every route, the refusals (record 0700)."""

import threading
from pathlib import Path
from typing import Any

import pytest

from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.pipeline import RunSettings
from actuarycanary.ui.runner import CACHE_NAME, STAGES

from .conftest import BASELINE_TINY, MESSY, Client, stages_then


def form(**values: str) -> dict[str, Any]:
    return {"form": {"folder": str(BASELINE_TINY), **values}}


# --- the token and the address ----------------------------------------------------------------


def test_a_request_without_the_token_is_refused(make_server) -> None:
    client: Client = make_server()
    for path in ("/", "/api/state", "/static/app.js", "/report?run=x"):
        status, _, body = client.get(path, token=None)
        assert status == 403 and body == b"Forbidden", path
    assert client.request("POST", "/api/quit", {}, token=None)[0] == 403


def test_a_wrong_token_is_refused(make_server) -> None:
    client: Client = make_server()
    assert client.get("/api/state", token="wrong")[0] == 403
    assert client.get("/api/state", token=client.server.token + "x")[0] == 403
    assert client.get("/api/state", token="")[0] == 403


def test_the_token_may_come_in_the_address(make_server) -> None:
    client: Client = make_server()
    assert client.get(f"/api/state?t={client.server.token}", token=None)[0] == 200
    assert client.get("/api/state?t=nope", token=None)[0] == 403


def test_a_request_for_another_host_name_is_refused(make_server) -> None:
    client: Client = make_server()
    assert client.get("/api/state", host="evil.example")[0] == 403
    assert client.get("/api/state", host=f"evil.example:{client.server.port}")[0] == 403
    assert client.get("/api/state", host=f"localhost:{client.server.port}")[0] == 200


def test_the_server_listens_on_this_computer_only(make_server) -> None:
    client: Client = make_server()
    assert client.server.server_address[0] == "127.0.0.1"
    assert client.server.port > 0
    assert client.server.url("tr").startswith(f"http://127.0.0.1:{client.server.port}/?t=")


def test_each_start_has_its_own_random_token(make_server) -> None:
    first: Client = make_server()
    second: Client = make_server()
    assert first.server.token != second.server.token and len(first.server.token) >= 20
    assert second.get("/api/state", token=first.server.token)[0] == 403


# --- the page and its files -------------------------------------------------------------------


def test_the_page_comes_in_both_languages_with_privacy_headers(make_server) -> None:
    client: Client = make_server()
    status, headers, body = client.get("/")
    page = body.decode("utf-8")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert '<html lang="en">' in page and "Check the files" in page
    assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
    _, _, turkish = client.get("/?lang=tr")
    assert '<html lang="tr">' in turkish.decode(
        "utf-8"
    ) and "Dosyaları kontrol et" in turkish.decode("utf-8")
    _, _, other = client.get("/?lang=de")
    assert '<html lang="en">' in other.decode("utf-8")


def test_the_two_static_files_are_served_and_nothing_else(make_server) -> None:
    client: Client = make_server()
    status, headers, body = client.get("/static/app.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript") and body
    status, headers, _ = client.get("/static/app.css")
    assert status == 200 and headers["Content-Type"].startswith("text/css")
    for name in ("server.py", "../server.py", "..%2Fserver.py", "strings.yaml", ""):
        assert client.get(f"/static/{name}")[0] == 404, name
    assert client.get("/nothing")[0] == 404 and client.get("/api/nothing")[0] == 404
    assert client.get("/api/__class__")[0] == 404 and client.get("/api/_start")[0] == 404


def test_a_bad_body_is_a_message_not_a_crash(make_server) -> None:
    client: Client = make_server()
    status, _, body = client.request("POST", "/api/command", None, headers={"Content-Length": "x"})
    assert status == 413
    status, answer = client.post("/api/scan", ["not", "an", "object"])
    assert status == 400 and answer["error"]["code"] == "bad_request"


# --- state, browse, command -------------------------------------------------------------------


def test_the_state_tells_the_defaults_and_that_no_run_is_going(make_server, tmp_path: Path) -> None:
    client: Client = make_server()
    status, state = client.get_json("/api/state")
    assert status == 200 and state["run"] == {"state": "idle"}
    assert state["out"] == str(tmp_path / "out") and state["profiles"] == str(tmp_path / "profiles")


def test_browse_lists_roots_then_folders(make_server, tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "premiums.xlsx").write_bytes(b"")
    client: Client = make_server()
    status, roots = client.get_json("/api/browse")
    assert status == 200 and roots["roots"]
    status, shown = client.get_json(f"/api/browse?path={tmp_path}")
    assert status == 200
    assert [f["name"] for f in shown["folders"]] == ["data"]
    assert shown["folders"][0]["counts"] == {"spreadsheets": 1, "csv": 0}


def test_browse_of_a_path_that_does_not_exist_is_refused(make_server, tmp_path: Path) -> None:
    client: Client = make_server()
    status, answer = client.get_json(f"/api/browse?path={tmp_path / 'nowhere'}")
    assert status == 404 and answer["error"]["code"] == "folder_missing"


def test_the_command_line_of_the_choices(make_server, tmp_path: Path) -> None:
    client: Client = make_server(default_out="out", default_profiles="profiles")
    status, answer = client.post("/api/command", {**form(lang="tr"), "pending": True})
    assert status == 200
    assert answer["command"] == f"canary run {BASELINE_TINY} --lang tr --yes"
    other = {"out": str(tmp_path / "results"), "profiles": ""}
    shown = client.post("/api/command", form(**other))[1]["command"]
    assert f"--out {tmp_path / 'results'}" in shown and "--profiles" not in shown


# --- scan and mapping -------------------------------------------------------------------------


def test_scan_of_the_tiny_baseline(make_server, messy_out: Path) -> None:
    client: Client = make_server()
    status, shown = client.post("/api/scan", form(out=str(messy_out)))
    assert status == 200 and shown["pending"] == 0
    names = [f["name"] for f in shown["files"]]
    assert "claim_valuations.xlsx" in names and all(f["recognised"] for f in shown["files"])
    assert {c["concept"] for c in shown["concepts"]} >= {"claim_valuations", "premiums"}
    assert shown["profiles"].endswith("profiles")


@pytest.mark.parametrize(
    ("folder", "code"),
    [("", "folder_empty"), ("{tmp}/nowhere", "folder_missing"), ("{tmp}", "no_spreadsheets")],
)
def test_scan_refusals(make_server, tmp_path: Path, folder: str, code: str) -> None:
    client: Client = make_server()
    status, answer = client.post("/api/scan", {"form": {"folder": folder.format(tmp=tmp_path)}})
    assert status == 400 and answer["error"]["code"] == code


def test_a_csv_only_folder_has_no_spreadsheets(make_server, tmp_path: Path) -> None:
    (tmp_path / "claims.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    client: Client = make_server()
    status, answer = client.post("/api/scan", {"form": {"folder": str(tmp_path)}})
    assert status == 400 and answer["error"]["code"] == "no_spreadsheets"


def test_a_mapping_edit_round_trip_through_the_interface(
    make_server, messy_out: Path, messy_one: Path
) -> None:
    client: Client = make_server()
    where = {"folder": str(messy_one), "out": str(messy_out)}
    status, shown = client.post("/api/scan", {"form": where})
    assert status == 200 and shown["pending"] > 0
    sheet = next(
        s for f in shown["files"] for s in f["sheets"] if s["file"] == "claim_valuations.xlsx"
    )
    assert sheet["state"] == "proposed" and sheet["editable"]
    columns = {m["source"]: m["field"] for m in sheet["mappings"] if not m["personal"]}
    columns["RUCU TAHSILAT "] = None
    choice = {"file": sheet["file"], "sheet": sheet["sheet"], "concept": sheet["concept"],
              "amounts": sheet["amounts"], "columns": columns}  # fmt: skip
    status, saved = client.post("/api/mapping", {"form": where, "sheets": [choice]})
    assert status == 200 and len(saved["saved"]) == 1
    assert Path(saved["saved"][0]).parent == Path(saved["profiles"])
    after = next(s for f in saved["files"] for s in f["sheets"] if s["file"] == sheet["file"])
    assert after["state"] == "saved"
    assert next(m for m in after["mappings"] if m["source"] == "RUCU TAHSILAT ")["field"] is None
    assert saved["pending"] == shown["pending"] - 1 == 0
    # a second scan, as the next run would make it, finds the profile
    again = client.post("/api/scan", {"form": where})[1]
    assert (
        next(s for f in again["files"] for s in f["sheets"] if s["file"] == sheet["file"])["state"]
        == "saved"
    )


def test_changing_the_concept_of_one_sheet(make_server, messy_out: Path) -> None:
    client: Client = make_server()
    where = {"folder": str(MESSY), "out": str(messy_out)}
    status, answer = client.post(
        "/api/sheet", {"form": where, "file": "expenses.xlsx", "sheet": "Giderler", "concept": None}
    )
    assert status == 200 and answer["concept"] is None
    status, answer = client.post(
        "/api/sheet", {"form": where, "file": "nope.xlsx", "sheet": "x", "concept": None}
    )
    assert status == 400 and answer["error"]["code"] == "sheet_missing"


# --- runs -------------------------------------------------------------------------------------


def test_start_runs_the_pipeline_with_the_settings_of_the_form(
    make_server, calls: list[dict[str, Any]], default_run, tmp_path: Path
) -> None:
    client: Client = make_server(stages_then(default_run))
    status, answer = client.post("/api/start", form(lang="tr", out=str(tmp_path / "o")))
    assert status == 200 and answer["started"]
    client.server.manager.wait(10)
    (call,) = calls
    assert call["settings"] == RunSettings(language="tr") and call["confirm"] is None
    assert call["out"] == tmp_path / "o" and call["cache_dir"] == tmp_path / "o" / CACHE_NAME
    assert call["profiles_dir"] == tmp_path / "profiles"
    status, run = client.get_json("/api/run")
    assert run["state"] == "done" and run["run_id"] == default_run.run_id
    assert [s["name"] for s in run["stages"]] == list(STAGES)


def test_a_second_start_while_a_run_goes_is_refused_with_a_message(
    make_server, default_run
) -> None:
    release = threading.Event()

    def slow(folder, out, settings, **options):
        options["progress"](STAGES[0])
        release.wait(10)
        return default_run

    client: Client = make_server(slow)
    assert client.post("/api/start", form())[0] == 200
    status, answer = client.post("/api/start", form())
    assert status == 409 and answer["error"]["code"] == "run_busy"
    assert client.post("/api/demo", {"lang": "en"})[0] == 409
    assert client.post("/api/quit", {})[0] == 409  # a run is going: not without force
    assert client.post("/api/cancel")[1] == {"cancel_requested": True}
    release.set()
    client.server.manager.wait(10)


def test_start_refusals(make_server, tmp_path: Path, calls: list[dict[str, Any]]) -> None:
    client: Client = make_server()
    for body, code in (
        ({"form": {"folder": ""}}, "folder_empty"),
        ({"form": {"folder": str(tmp_path / "nowhere")}}, "folder_missing"),
        ({"form": {"folder": str(tmp_path)}}, "no_spreadsheets"),
        (form(lang="de"), "settings_rejected"),
        (form(value="discounted", discount_date="31.12.2025"), "settings_rejected"),
        (form(out=str(BASELINE_TINY / "claim_valuations.xlsx")), "out_invalid"),
    ):
        status, answer = client.post("/api/start", body)
        assert status == 400 and answer["error"]["code"] == code, body
    assert calls == []  # none of them reached the pipeline


def test_the_demo_is_the_demo_of_the_command_line(
    make_server, calls: list[dict[str, Any]], default_run
) -> None:
    client: Client = make_server(stages_then(default_run))
    status, answer = client.post("/api/demo", {"lang": "en"})
    assert status == 200
    client.server.manager.wait(10)
    (call,) = calls
    assert call["settings"] == RunSettings(discount=DiscountSettings(curve_id="TRY_GOV"))
    assert call["folder"].name == "demo" and (call["folder"] / "claim_valuations.xlsx").is_file()
    assert Path(answer["out"]).name.startswith("canary-demo-") and call["out"] == Path(
        answer["out"]
    )
    assert client.post("/api/demo", {"lang": "de"})[1]["error"]["code"] == "bad_request"


def test_a_failed_run_shows_the_message_of_the_terminal(make_server) -> None:
    from actuarycanary.pipeline import InputError

    def failing(folder, out, settings, **options):
        options["progress"](STAGES[0])
        raise InputError(f"{folder}: no sheet was recognised as claim_valuations")

    client: Client = make_server(failing)
    client.post("/api/start", form())
    client.server.manager.wait(10)
    run = client.get_json("/api/run")[1]
    assert (
        run["state"] == "failed" and "no sheet was recognised as claim_valuations" in run["error"]
    )


def test_cancel_with_no_run_is_a_plain_no(make_server) -> None:
    client: Client = make_server()
    assert client.post("/api/cancel")[1] == {"cancel_requested": False}


# --- result, past runs, report, folder --------------------------------------------------------


def test_the_result_reads_the_run_folder(make_server, default_run) -> None:
    client: Client = make_server()
    out = default_run.folder.parent
    status, result = client.get_json(f"/api/result?out={out}&run={default_run.run_id}")
    assert status == 200 and result["run_id"] == default_run.run_id and result["report"]
    assert result["settings"]["language"] == "en" and result["settings"]["cut_off"] == "2025-12-31"
    lines = {(r["segment"], r["line"]) for r in result["headline"]}
    assert ("NON_LIFE", "MOTOR_TPL") in lines and len(lines) == 4
    assert result["findings"]["counts"]["WARNING"] >= 1 and result["findings"]["findings"]
    assert result["inputs"] and result["outputs"] > 10


def test_the_headline_numbers_are_the_ones_the_terminal_prints(make_server, default_run) -> None:
    client: Client = make_server()
    out = default_run.folder.parent
    result = client.get_json(f"/api/result?out={out}&run={default_run.run_id}")[1]
    by_line = {(r["segment"], r["line"]): r for r in result["headline"]}
    for group in default_run.reserving.groups:
        totals = group.totals()
        row = by_line[(group.group[0], group.group[1])]
        assert row["paid"] == pytest.approx(totals.paid, abs=1e-6)
        assert row["incurred"] == pytest.approx(totals.incurred, abs=1e-6)
        assert row["ultimate"] == pytest.approx(totals.ultimate["incurred"], abs=1e-6)
        assert row["ibnr"] == pytest.approx(totals.ibnr("incurred"), abs=1e-6)


def test_past_runs_list_the_run_folders(make_server, default_run, tmp_path: Path) -> None:
    (default_run.folder.parent / "not-a-run").mkdir(exist_ok=True)
    client: Client = make_server()
    out = default_run.folder.parent
    status, listed = client.get_json(f"/api/runs?out={out}")
    assert status == 200 and [r["run_id"] for r in listed["runs"]] == [default_run.run_id]
    row = listed["runs"][0]
    assert row["language"] == "en" and row["reinsurance"] == "GROSS" and row["value"] == "NOMINAL"
    assert row["date"] and row["has_report"]
    assert client.get_json(f"/api/runs?out={tmp_path / 'nowhere'}")[1]["runs"] == []


@pytest.mark.parametrize("run", ["", "x", "../x", "..\\x", "0123456789abcdeg", "0123456789abcdef0"])
def test_a_run_id_is_an_id_and_not_a_path(make_server, default_run, run: str) -> None:
    client: Client = make_server()
    out = default_run.folder.parent
    assert client.get_json(f"/api/result?out={out}&run={run}")[0] == 404
    assert client.get(f"/report?out={out}&run={run}")[0] == 404
    assert client.post("/api/open", {"out": str(out), "run": run})[0] == 404


def test_the_report_is_served_from_the_run_folder(make_server, default_run) -> None:
    client: Client = make_server()
    out = default_run.folder.parent
    status, headers, body = client.get(f"/report?out={out}&run={default_run.run_id}")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert body == (default_run.folder / "report.html").read_bytes()
    assert client.get(f"/report?out={out}&run=ffffffffffffffff")[0] == 404


def test_open_folder_opens_a_run_folder_and_nothing_else(
    make_server, default_run, opened: list[Path], tmp_path: Path
) -> None:
    client: Client = make_server()
    out = default_run.folder.parent
    status, answer = client.post("/api/open", {"out": str(out), "run": default_run.run_id})
    assert status == 200 and opened == [default_run.folder]
    assert client.post("/api/open", {"out": str(tmp_path), "run": "0123456789abcdef"})[0] == 404
    assert opened == [default_run.folder]


def test_quit_stops_the_server(make_server) -> None:
    client: Client = make_server()
    status, answer = client.post("/api/quit", {})
    assert status == 200 and answer == {"quitting": True}
    for _ in range(100):
        if client.server._BaseServer__is_shut_down.is_set():  # type: ignore[attr-defined]
            break
        threading.Event().wait(0.05)
    assert client.server._BaseServer__is_shut_down.is_set()  # type: ignore[attr-defined]
