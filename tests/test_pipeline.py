"""End to end on the tiny baseline: the run completes and reproduces its outputs."""

import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.io.excel import RawTable
from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.pipeline import InputError, RunResult, RunSettings, run
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.tables import TableRecognition
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSettings

BASELINE = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"

pytestmark = pytest.mark.integration


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.slow
def test_baseline_tiny_reproduces(tmp_path: Path, cache: Path, default_run: RunResult) -> None:
    first = default_run
    second = run(BASELINE, tmp_path / "b", cache_dir=cache)
    assert first.run_id == second.run_id
    assert first.folder.name == first.run_id
    assert second.folder == tmp_path / "b" / second.run_id
    one, two = _manifest(first.manifest), _manifest(second.manifest)
    assert one["outputs"] == two["outputs"]
    assert first.manifest.read_bytes() == second.manifest.read_bytes()


def test_baseline_tiny_outputs_inputs_and_groups(default_run: RunResult) -> None:
    first = default_run
    assert first.folder.name == first.run_id
    one = _manifest(first.manifest)
    assert [o["name"] for o in one["outputs"]] == [
        "report.html",
        "quality.json",
        "triangles.csv",
        "factors.csv",
        "chain_ladder.csv",
        "measures.csv",
        "lineage.csv",
        "modules.json",
        "assumptions.csv",
        "ultimates.csv",
        "reserve_range.csv",
        "cash_flows.csv",
        "diagnostics.csv",
        "anomalies.csv",
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


@pytest.mark.slow
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


@pytest.mark.slow
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


def test_manifest_records_the_cut_off_used_next_to_the_setting(default_run: RunResult) -> None:
    latest = _manifest(default_run.manifest)
    assert latest["settings"]["triangles"]["cut_off"] is None
    assert latest["settings"]["triangles"]["cut_off_used"] == "2025-12-31"


@pytest.mark.slow
def test_a_given_cut_off_is_recorded_as_given_and_as_used(tmp_path: Path, cache: Path) -> None:
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
    default_run: RunResult,
) -> None:
    """Decision 0052: conversion is on by default."""
    assert _manifest(default_run.manifest)["settings"]["bases"]["currency_conversion"] == "market"
    assert default_run.reserving.triangles.not_converted.height == 0


@pytest.mark.slow
def test_without_conversion_foreign_currencies_are_reported_apart(
    tmp_path: Path, cache: Path, default_run: RunResult
) -> None:
    """`use_market=False` brings back the apart view."""
    apart = run(BASELINE, tmp_path / "a", RunSettings(use_market=False), cache_dir=cache)
    assert apart.reserving.triangles.not_converted.height > 0
    assert _manifest(apart.manifest)["settings"]["bases"]["currency_conversion"] == "none"
    assert apart.run_id != default_run.run_id


@pytest.mark.slow
def test_without_a_market_sheet_nothing_is_converted_and_says_so(
    tmp_path: Path, cache: Path
) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    result = run(folder, tmp_path / "out", cache_dir=cache)
    assert _manifest(result.manifest)["settings"]["bases"]["currency_conversion"] == "none"


def test_run_says_which_modules_ran_and_why_others_did_not(default_run: RunResult) -> None:
    states = {m.module: m.state.value for m in default_run.analysis.modules}
    assert states == {
        "M01": "ran",
        "M02": "ran",
        "M03": "ran",
        "M04": "limited",
        "M05": "ran",
        "M06": "limited",
    }
    # the 4 x 4 triangles of the tiny baseline are too small for the Mack variance (record 0041)
    assert "MT06 Mack standard error did not run" in " ".join(
        default_run.analysis.get("M04").reasons
    )
    assert default_run.analysis.get("M04").methods_missing == ()
    listed = json.loads((default_run.folder / "modules.json").read_text(encoding="utf-8"))
    assert [m["module"] for m in listed["modules"]] == ["M01", "M02", "M03", "M04", "M05", "M06"]


@pytest.mark.slow
def test_modules_without_their_files_are_skipped_with_the_reason(
    tmp_path: Path, cache: Path
) -> None:
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


def _csv(result: RunResult, name: str) -> pl.DataFrame:
    return pl.read_csv((result.folder / name), infer_schema_length=0)


def test_the_methods_are_wired_so_that_the_measures_that_waited_for_them_are_available(
    default_run: RunResult,
) -> None:
    listed = json.loads((default_run.folder / "modules.json").read_text(encoding="utf-8"))
    views = {
        (m["measure"], m["available"]) for module in listed["modules"] for m in module["measures"]
    }
    for measure in ("RS01", "RS02", "RS03", "AE01", "RT01", "RT02"):
        assert (measure, True) in views, measure
    assert set(listed["methods_run"]) >= {"MT01", "MT02", "MT03", "MT04", "MT05", "MT07", "MT10"}
    m04 = default_run.analysis.get("M04")
    assert m04.methods_missing == () and "MT10" in m04.methods_built
    # RT02 now carries the ultimate loss ratio of the selection
    values = _csv(default_run, "measures.csv")
    assert (
        values.filter(
            (pl.col("measure") == "RT02") & (pl.col("column") == "ultimate_loss_ratio")
        ).height
        > 0
    )
    assert (
        values.filter((pl.col("measure") == "RT01") & (pl.col("column") == "ultimate_ratio")).height
        > 0
    )


def test_assumptions_diagnostics_and_anomalies_are_written_and_listed_in_the_manifest(
    default_run: RunResult,
) -> None:
    manifest = _manifest(default_run.manifest)
    assumptions = _csv(default_run, "assumptions.csv")
    assert assumptions.columns == [
        "method", "name", "scope", "target", "value", "default", "who", "when", "why"
    ]  # fmt: skip
    assert set(assumptions["who"]) == {"default"}  # no register was given
    assert {"MT02", "MT03", "MT05", "MT10"} <= set(assumptions["method"])
    assert len(manifest["assumptions"]) == assumptions.height
    assert manifest["assumptions"][0]["who"] == "default"
    assert manifest["settings"]["assumptions"] == {"entries": []}
    assert manifest["settings"]["methods"]["robust_z"]["threshold"] == 3.5
    assert manifest["randomness"] == [{"method": "MT09", "seed": 1, "purpose": "isolation forest"}]
    ids = {s["id"] for s in manifest["specs"]}
    assert {"MT03", "MT04", "MT05", "MT07", "MT08", "MT09", "MT10", "PR02"} <= ids
    assert "MT06" not in ids  # the Mack variance did not run on the 4 x 4 triangles

    diagnostics = _csv(default_run, "diagnostics.csv")
    counts = default_run.reserving.diagnostics_by_group()
    assert diagnostics.height == sum(counts.values())
    listed = json.loads((default_run.folder / "modules.json").read_text(encoding="utf-8"))
    assert {(d["segment"], d["line"]): d["count"] for d in listed["diagnostics"]} == counts
    assert {"THIN_EVIDENCE", "FEW_LINK_RATIOS", "LATE_DEVELOPMENT", "NEGATIVE_IBNR"} <= set(
        diagnostics["code"]
    )

    anomalies = _csv(default_run, "anomalies.csv")
    assert anomalies.height == default_run.anomalies.flags.height > 0
    assert anomalies.filter(pl.col("rows").is_null()).height == 0  # every flag names its rows
    assert {"MT08", "MT09"} == set(anomalies["method"])


@pytest.mark.slow
def test_a_different_assumption_gives_a_different_run_id(
    tmp_path: Path, cache: Path, default_run: RunResult
) -> None:
    register = AssumptionsRegister(
        entries=(
            Assumption(
                method="MT02",
                name="tail_factor",
                scope="*",
                value=1.05,
                who="reviewer",
                when=date(2026, 1, 5),
                why="the tail of the line is longer than the triangle",
            ),
        )
    )
    changed = run(BASELINE, tmp_path / "a", RunSettings(assumptions=register), cache_dir=cache)
    assert changed.run_id != default_run.run_id
    manifest = _manifest(changed.manifest)
    assert manifest["settings"]["assumptions"]["entries"][0]["who"] == "reviewer"
    used = [a for a in manifest["assumptions"] if a["who"] == "reviewer"]
    assert len(used) == 8 and {a["value"] for a in used} == {1.05}  # four groups, two triangles
    assert _csv(changed, "assumptions.csv").filter(pl.col("who") == "reviewer").height == 8
    ultimate = lambda r: r.reserving.groups[0].chain_ladder["paid"].ultimate  # noqa: E731
    assert ultimate(changed)[0] == pytest.approx(ultimate(default_run)[0] * 1.05)


@pytest.mark.slow
def test_the_report_shows_the_modules_and_the_method_tables(default_run: RunResult) -> None:
    """Reading the 5 MB page (plotly is inlined) takes over a second on a scanned disk."""
    html = default_run.report.read_text(encoding="utf-8")
    assert 'id="modules"' in html
    for heading in ("Ultimates by method", "Diagnostics", "Assumptions in force", "Anomaly flags"):
        assert heading in html
