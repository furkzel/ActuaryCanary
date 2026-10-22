"""End to end on the tiny baseline: the run completes and reproduces its outputs."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from actuarycanary.io.excel import RawTable
from actuarycanary.pipeline import InputError, RunResult, RunSettings, run
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.tables import TableRecognition
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSettings

BASELINE = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache")


@pytest.fixture(scope="module")
def default_run(tmp_path_factory: pytest.TempPathFactory, cache: Path) -> RunResult:
    """The default run of the tiny baseline, made once for the tests that compare against it."""
    return run(BASELINE, tmp_path_factory.mktemp("default"), cache_dir=cache)


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_baseline_tiny_runs_and_reproduces(
    tmp_path: Path, cache: Path, default_run: RunResult
) -> None:
    first = default_run
    second = run(BASELINE, tmp_path / "b", cache_dir=cache)
    assert first.run_id == second.run_id
    assert first.folder.name == first.run_id
    assert second.folder == tmp_path / "b" / second.run_id
    one, two = _manifest(first.manifest), _manifest(second.manifest)
    assert one["outputs"] == two["outputs"]
    assert first.manifest.read_bytes() == second.manifest.read_bytes()
    assert [o["name"] for o in one["outputs"]] == [
        "report.html",
        "quality.json",
        "triangles.csv",
        "factors.csv",
        "chain_ladder.csv",
        "measures.csv",
        "lineage.csv",
        "modules.json",
    ]
    assert [i["name"] for i in one["inputs"]] == [
        "claim_valuations.xlsx",
        "claims.xlsx",
        "market.xlsx",
        "policies.xlsx",
        "premiums.xlsx",
        "expenses.xlsx",
    ]
    assert {"MT01", "MT02", "claim_valuations", "claims"} <= {s["id"] for s in one["specs"]}
    assert one["settings"]["triangles"]["origin_period"] == "YEAR"
    rules = {f["rule"] for f in one["data_findings"]}
    assert {"DV-CLV-03", "DV-CLV-04", "DV-CLV-06"} <= rules  # injected faults are found
    groups = {g.group for g in first.reserving.groups}
    assert groups == {
        ("LIFE", "GROUP_TERM_LIFE"),
        ("NON_LIFE", "MOTOR_OD"),
        ("NON_LIFE", "MOTOR_TPL"),
        ("NON_LIFE", "PROPERTY"),
    }


def test_settings_change_the_run_id(tmp_path: Path, cache: Path, default_run: RunResult) -> None:
    yearly = default_run
    quarterly = run(
        BASELINE,
        tmp_path / "q",
        RunSettings(triangles=TriangleSettings(development_period=Period.QUARTER)),
        cache_dir=cache,
    )
    assert quarterly.run_id != yearly.run_id
    assert quarterly.reserving.groups[0].triangles["paid"].ages[:2] == (3, 6)


def test_claim_valuations_alone_use_proxy_origins(tmp_path: Path, cache: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    result = run(folder, tmp_path / "out", cache_dir=cache)
    assert result.reserving.triangles.origin_basis == "first_valuation (proxy)"
    assert "claims" not in {s["id"] for s in _manifest(result.manifest)["specs"]}


def test_missing_claim_valuations_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="claim_valuations.xlsx"):
        run(tmp_path, tmp_path / "out", cache_dir=None)


MESSY = Path(__file__).parent / "fixtures" / "synthetic" / "messy_headers"


def _values_without_quality(result: RunResult) -> list[str]:
    lines = (result.folder / "measures.csv").read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.startswith("DQ01,")]


def _accept(
    pending: list[tuple[TableRecognition, RawTable]], dictionary: Dictionary
) -> list[TableRecognition]:
    return [rec for rec, _ in pending]


@pytest.mark.slow
def test_messy_layout_gives_the_baseline_results(tmp_path: Path, cache: Path) -> None:
    baseline = run(BASELINE, tmp_path / "b", cache_dir=cache)
    messy = run(MESSY, tmp_path / "m", cache_dir=cache)
    assert messy.run_id != baseline.run_id
    for name in ("triangles.csv", "factors.csv", "chain_ladder.csv"):
        assert (messy.folder / name).read_bytes() == (baseline.folder / name).read_bytes()
    # the measures agree too, except the quality score, which sees the layout faults
    assert _values_without_quality(messy) == _values_without_quality(baseline)
    manifest = _manifest(messy.manifest)
    assert [i["name"] for i in manifest["inputs"]] == [
        "claim_valuations.xlsx",
        "claims.xlsx",
        "market.xlsx",
        "policies.xlsx",
        "premiums.xlsx",
        "expenses.xlsx",
    ]
    claims = next(m for m in manifest["mapping_profiles"] if m["concept"] == "claims")
    assert claims["header_row"] == 3 and claims["rows_above_header"] == 2
    assert sorted(claims["personal_data_dropped"]) == ["MUSTERI_NO", "SIGORTALI_ADI", "TCKN"]
    assert claims["source"] == "automatic" and claims["profile_sha256"] is None
    valuations = next(m for m in manifest["mapping_profiles"] if m["concept"] == "claim_valuations")
    assert {u["label"] for u in valuations["unmapped_labels"]} == {"???", "PEND-REV"}
    assert manifest["tables_not_used"] == []  # every sheet is read now


def test_manifest_records_the_cut_off_used_next_to_the_setting(
    tmp_path: Path, cache: Path, default_run: RunResult
) -> None:
    latest = _manifest(default_run.manifest)
    assert latest["settings"]["triangles"]["cut_off"] is None
    assert latest["settings"]["triangles"]["cut_off_used"] == "2025-12-31"
    chosen = RunSettings(triangles=TriangleSettings(cut_off=date(2024, 12, 15)))
    given = _manifest(run(BASELINE, tmp_path / "b", chosen, cache_dir=cache).manifest)
    assert given["settings"]["triangles"]["cut_off"] == "2024-12-15"
    assert given["settings"]["triangles"]["cut_off_used"] == "2024-12-31"


@pytest.mark.slow
def test_profiles_are_saved_reused_and_an_edit_changes_the_run_id(
    tmp_path: Path, cache: Path
) -> None:
    profiles = tmp_path / "profiles"
    asked: list[int] = []

    def confirm(
        pending: list[tuple[TableRecognition, RawTable]], dictionary: Dictionary
    ) -> list[TableRecognition]:
        asked.append(len(pending))
        return _accept(pending, dictionary)

    first = run(MESSY, tmp_path / "1", cache_dir=cache, profiles_dir=profiles, confirm=confirm)
    second = run(MESSY, tmp_path / "2", cache_dir=cache, profiles_dir=profiles, confirm=confirm)
    assert asked == [7]  # six files, market on two sheets; the second run asks nothing
    assert len(list(profiles.glob("*.yaml"))) == 7
    assert {str(t.source) for t in first.tables} == {"confirmed"}
    assert {str(t.source) for t in second.tables} == {"saved"}
    assert second.run_id == first.run_id  # same mapping, however it was confirmed

    record = next(
        m for m in _manifest(second.manifest)["mapping_profiles"] if m["concept"] == "claims"
    )
    path = profiles / f"{record['fingerprint']}.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("field: cause", "field: null"), encoding="utf-8"
    )
    edited = run(MESSY, tmp_path / "3", cache_dir=cache, profiles_dir=profiles, confirm=confirm)
    assert edited.run_id != first.run_id
    claims = next(
        m for m in _manifest(edited.manifest)["mapping_profiles"] if m["concept"] == "claims"
    )
    assert "NEDEN" in claims["columns_not_used"]
    assert claims["profile_sha256"] != record["profile_sha256"]


def test_default_run_converts_foreign_currencies_when_the_folder_has_market_data(
    tmp_path: Path, cache: Path, default_run: RunResult
) -> None:
    """Decision 0052: conversion is on by default; `use_market=False` brings back the apart view."""
    assert _manifest(default_run.manifest)["settings"]["bases"]["currency_conversion"] == "market"
    assert default_run.reserving.triangles.not_converted.height == 0
    apart = run(BASELINE, tmp_path / "a", RunSettings(use_market=False), cache_dir=cache)
    assert apart.reserving.triangles.not_converted.height > 0
    assert _manifest(apart.manifest)["settings"]["bases"]["currency_conversion"] == "none"
    assert apart.run_id != default_run.run_id


def test_without_a_market_sheet_nothing_is_converted_and_says_so(
    tmp_path: Path, cache: Path
) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    result = run(folder, tmp_path / "out", cache_dir=cache)
    assert _manifest(result.manifest)["settings"]["bases"]["currency_conversion"] == "none"


def test_run_says_which_modules_ran_and_why_others_did_not(
    tmp_path: Path, cache: Path, default_run: RunResult
) -> None:
    states = {m.module: m.state.value for m in default_run.analysis.modules}
    assert states == {
        "M01": "ran",
        "M02": "ran",
        "M03": "ran",
        "M04": "limited",
        "M05": "limited",
        "M06": "limited",
    }
    assert "methods not built yet" in " ".join(default_run.analysis.get("M04").reasons)
    listed = json.loads((default_run.folder / "modules.json").read_text(encoding="utf-8"))
    assert [m["module"] for m in listed["modules"]] == ["M01", "M02", "M03", "M04", "M05", "M06"]
    assert 'id="modules"' in default_run.report.read_text(encoding="utf-8")

    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    alone = run(folder, tmp_path / "out", cache_dir=cache)
    reasons = {m.module: m.reasons for m in alone.analysis.modules if m.state.value == "skipped"}
    assert set(reasons) == {"M02", "M05"}
    assert "no premium file was loaded" in reasons["M02"][0]
    assert "premiums" in reasons["M05"][0]


def test_every_value_in_the_outputs_names_its_spec_version_and_its_source_rows(
    default_run: RunResult,
) -> None:
    values = (default_run.folder / "measures.csv").read_text(encoding="utf-8").splitlines()
    assert values[0].startswith("measure,version,view,basis,row,key,column,value,note")
    assert any(line.startswith("PR02,1.0.0,") for line in values)
    lineage = (default_run.folder / "lineage.csv").read_text(encoding="utf-8").splitlines()
    assert lineage[0] == "measure,version,view,row,concept,file,sheet,rows,count"
    assert any(",premiums,premiums.xlsx," in line for line in lineage)
