"""End to end on the tiny baseline: the run completes and reproduces its outputs."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from actuarycanary.io.excel import RawTable
from actuarycanary.pipeline import InputError, RunSettings, run
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.tables import TableRecognition
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSettings

BASELINE = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache")


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_baseline_tiny_runs_and_reproduces(tmp_path: Path, cache: Path) -> None:
    first = run(BASELINE, tmp_path / "a", cache_dir=cache)
    second = run(BASELINE, tmp_path / "b", cache_dir=cache)
    assert first.run_id == second.run_id
    assert first.folder == tmp_path / "a" / first.run_id
    one, two = _manifest(first.manifest), _manifest(second.manifest)
    assert one["outputs"] == two["outputs"]
    assert first.manifest.read_bytes() == second.manifest.read_bytes()
    assert [o["name"] for o in one["outputs"]] == [
        "report.html",
        "triangles.csv",
        "factors.csv",
        "chain_ladder.csv",
    ]
    assert [i["name"] for i in one["inputs"]] == ["claim_valuations.xlsx", "claims.xlsx"]
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


def test_settings_change_the_run_id(tmp_path: Path, cache: Path) -> None:
    yearly = run(BASELINE, tmp_path / "y", cache_dir=cache)
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
    manifest = _manifest(messy.manifest)
    assert [i["name"] for i in manifest["inputs"]] == ["claim_valuations.xlsx", "claims.xlsx"]
    claims = next(m for m in manifest["mapping_profiles"] if m["concept"] == "claims")
    assert claims["header_row"] == 3 and claims["rows_above_header"] == 2
    assert sorted(claims["personal_data_dropped"]) == ["MUSTERI_NO", "SIGORTALI_ADI", "TCKN"]
    assert claims["source"] == "automatic" and claims["profile_sha256"] is None
    valuations = next(m for m in manifest["mapping_profiles"] if m["concept"] == "claim_valuations")
    assert {u["label"] for u in valuations["unmapped_labels"]} == {"???", "PEND-REV"}
    assert {t["concept"] for t in manifest["tables_not_used"]} == {
        "expenses",
        "market",
        "policies",
        "premiums",
    }


def test_manifest_records_the_cut_off_used_next_to_the_setting(tmp_path: Path, cache: Path) -> None:
    latest = _manifest(run(BASELINE, tmp_path / "a", cache_dir=cache).manifest)
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
