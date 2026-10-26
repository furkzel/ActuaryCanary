# pyright: reportOptionalMemberAccess=false, reportArgumentType=false, reportAttributeAccessIssue=false
"""The tier B reserving methods, MT17 and MT18 and the large-loss section in a run (record 0620).

Spec IDs proved: MT11, MT12, MT13, MT14, MT15, MT16, MT17, MT18, MT22, AE02, CV08, M06. The tiny
baseline has four origin years, so MT11 and MT12 refuse and MT17 and MT18 refuse on most lines:
what a run does then is the point of the first tests. The medium run, where the methods fit, is
slow and skips without `data/synthetic/baseline/medium`.
"""

import json
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.manifest.metadata import ProjectMetadata, load_metadata
from actuarycanary.measures.claim_base import size_classes
from actuarycanary.measures.model import MeasureRequest
from actuarycanary.methods import registry
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.severity import LargeLossError, parse_large_loss
from actuarycanary.pipeline import RunResult, RunSettings, run

BASELINE = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"
MEDIUM = Path(__file__).parents[1] / "data" / "synthetic" / "baseline" / "medium"


def _manifest(result: RunResult) -> dict:
    return json.loads(result.manifest.read_text(encoding="utf-8"))


def _csv(result: RunResult, name: str) -> pl.DataFrame:
    return pl.read_csv(result.folder / name, infer_schema_length=None)


def test_a_method_that_cannot_run_is_listed_with_its_reason_and_gives_no_number(
    default_run: RunResult,
) -> None:
    reasons = " ".join(default_run.analysis.get("M04").reasons)
    assert "MT11 bootstrap did not run for 4 of 4 groups" in reasons
    assert "at least 5 origin periods" in reasons
    assert "MT12 Munich chain ladder did not run for 4 of 4 groups" in reasons
    ultimates = _csv(default_run, "tier_b_ultimates.csv")
    refused = ultimates.filter(pl.col("method") == "munich_chain_ladder")
    assert refused["ultimate"].null_count() == refused.height
    assert refused["note"].str.contains("at least 5 origin periods").all()
    summary = _csv(default_run, "bootstrap_summary.csv")
    assert summary["mean"].null_count() == summary.height  # not a single simulated figure
    assert not [f for f in (default_run.folder).glob("bootstrap_distribution_*")]
    listed = str(default_run.report_data["not_run"])  # the section "What did not run and why"
    assert "MT11 bootstrap did not run" in listed and "MT12 Munich chain ladder" in listed
    assert "MT17 severity fits did not run" in " ".join(default_run.analysis.get("M03").reasons)
    assert "MT18 extreme values did not run" in " ".join(default_run.analysis.get("M06").reasons)


def test_the_methods_that_ran_enter_the_manifest_with_their_seeds_and_defaults(
    default_run: RunResult,
) -> None:
    manifest = _manifest(default_run)
    ids = {s["id"] for s in manifest["specs"]}
    assert {"MT13", "MT14", "MT15", "MT16", "MT22", "AE02", "MT17"} <= ids
    assert not ids & {"MT11", "MT12", "MT18", "MT19"}  # did not run, or not built
    rows = {r["method"]: r for r in manifest["randomness"]}
    assert set(rows) == {"MT09", "MT17", "MT22"} and all(r["seed"] == 1 for r in rows.values())
    assert manifest["settings"]["tier_b"] == registry.settings(1)
    assert manifest["settings"]["severity"]["MT17"]["gof_bootstrap"] == 200
    assert manifest["settings"]["severity"]["MT18"]["min_exceedances"] == 50
    names = [o["name"] for o in manifest["outputs"]]
    assert "tier_b_parameters.csv" in names and "extreme_threshold_comparison.csv" in names


def test_the_parameters_of_every_method_are_in_the_assumptions_and_the_diagnostics_file(
    default_run: RunResult,
) -> None:
    assumptions = _csv(default_run, "assumptions.csv")
    methods = set(assumptions["method"])
    assert {"MT11", "MT12", "MT13", "MT14", "MT15", "MT16", "MT22", "MT17", "MT18"} <= methods
    assert set(assumptions["who"]) == {"default"}
    scopes = set(assumptions.filter(pl.col("method") == "MT17")["scope"])
    assert "NON_LIFE/MOTOR_OD/severity" in scopes
    diagnostics = _csv(default_run, "diagnostics.csv")
    assert {"MT13", "MT17"} <= set(diagnostics["method"])
    severity = diagnostics.filter(pl.col("measure") == "severity")
    assert set(severity["segment"]) >= {"LIFE", "NON_LIFE"}  # the group is split from the target
    manifest = _manifest(default_run)
    assert len(manifest["assumptions"]) == assumptions.height


def test_tier_a_tables_of_the_run_are_what_they_were(default_run: RunResult) -> None:
    """The tail of MT14 is fitted, not applied: the default tail of MT02 stays 1."""
    factors = _csv(default_run, "factors.csv")
    last = factors.group_by("segment", "line", "method").agg(pl.col("factor").last())
    assert last.height > 0 and (last["factor"] == 1.0).all()  # the tail factor
    for group in default_run.reserving.groups:
        assert all(
            c.tail_factor == 1.0 for c in group.chain_ladder.values() if not isinstance(c, Skipped)
        )


def test_the_back_test_and_its_errors_are_written_for_ae02(default_run: RunResult) -> None:
    table = _csv(default_run, "back_test.csv")
    assert {"error", "summary"} <= set(table["kind"])  # no range: the Mack fit needs 5 origins
    methods = set(table.filter(pl.col("kind") == "summary")["method"])
    assert methods == {"MT02", "MT03", "MT04", "MT05", "MT10"}
    port = default_run.analysis.inputs.methods
    ae02 = port.measure("AE02", "GROSS, REPORTING, NOMINAL")
    assert isinstance(ae02, pl.DataFrame) and set(ae02["kind"]) == {"error", "summary"}
    assert ae02.height == table.filter(pl.col("kind").is_in(["error", "summary"])).height


def test_mt16_ultimate_counts_cover_the_reported_non_nil_claims(default_run: RunResult) -> None:
    for group in default_run.reserving.groups:
        fs = group.tier_b.frequency_severity
        if isinstance(fs, Skipped):
            continue
        assert (fs.ultimate_counts >= fs.count_chain.latest - 1e-9).all()
        assert fs.value_basis == "INFLATION_ADJUSTED"  # the market sheet has the index
        assert fs.exposure is not None  # policies are loaded: CL05's earned exposure
        assert (fs.catastrophe_ultimate == 0).all()  # the tiny baseline has no event codes


def test_the_project_file_accepts_a_large_loss_section() -> None:
    base = load_metadata()
    assert base.large_loss is None
    given = base.model_dump() | {"large_loss": {"percentile": 0.95, "thresholds": {"A/B": 1e6}}}
    metadata = ProjectMetadata.model_validate(given)
    settings = parse_large_loss(metadata.large_loss)
    assert settings.percentile == 0.95 and settings.thresholds == {("A", "B"): 1e6}
    assert settings.manifest_record() == {
        "percentile": 0.95, "thresholds": {"A/B": 1e6}, "source": "project.yaml",
    }  # fmt: skip
    with pytest.raises(LargeLossError):
        parse_large_loss({"percentile": 1.5})


@pytest.mark.slow
def test_a_fixed_threshold_in_project_yaml_changes_the_large_class_and_the_manifest(
    tmp_path: Path, cache: Path, default_run: RunResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = load_metadata()
    lines = default_run.analysis.inputs.large_loss_thresholds
    assert lines == {} and default_run.analysis.inputs.large_loss_percentile == 0.99
    changed = base.model_copy(
        update={"large_loss": {"percentile": 0.9, "thresholds": {"NON_LIFE/MOTOR_OD": 1.0}}}
    )
    monkeypatch.setattr("actuarycanary.pipeline.load_metadata", lambda: changed)
    result = run(BASELINE, tmp_path / "out", cache_dir=cache)
    assert result.run_id != default_run.run_id
    record = _manifest(result)["settings"]["large_loss"]
    assert record == {
        "percentile": 0.9, "thresholds": {"NON_LIFE/MOTOR_OD": 1.0}, "source": "project.yaml",
    }  # fmt: skip
    inputs = result.analysis.inputs
    assert inputs.large_loss_thresholds == {("NON_LIFE", "MOTOR_OD"): 1.0}
    classes, _ = size_classes(inputs, MeasureRequest())
    thresholds = classes.select("threshold").unique().to_series().drop_nulls().to_list()
    assert 1.0 in thresholds  # the fixed amount replaces the percentile of that line
    before, _ = size_classes(default_run.analysis.inputs, MeasureRequest())
    large = lambda frame: frame.filter(pl.col("claim_size_class") == "LARGE").height  # noqa: E731
    assert large(classes) > large(before)  # every claim of the line is now above 1


@pytest.mark.slow
def test_a_changed_seed_or_default_is_another_run(
    tmp_path: Path, cache: Path, default_run: RunResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = registry.settings
    monkeypatch.setattr(
        "actuarycanary.pipeline.tier_b_registry.settings",
        lambda seed=1: {**original(seed), "seed": seed + 1},
    )
    other = run(BASELINE, tmp_path / "out", cache_dir=cache)
    assert other.run_id != default_run.run_id


@pytest.mark.slow
def test_on_the_medium_baseline_m06_shows_the_mt18_threshold_beside_cv08s_and_does_not_use_it(
    tmp_path: Path, cache: Path
) -> None:
    if not MEDIUM.is_dir():
        pytest.skip("run `just synth baseline medium` first")
    result = run(MEDIUM, tmp_path / "out", RunSettings(), cache_dir=cache)
    comparison = _csv(result, "extreme_threshold_comparison.csv")
    ran = comparison.filter(pl.col("extreme_value_threshold").is_not_null())
    assert ran.height > 0  # MT18 found a threshold for at least one line
    note = result.analysis.inputs.extreme_value_note
    assert note.startswith("MT18 extreme-value threshold beside the CV08") and "not used" in note
    cl12 = next(m for m in result.analysis.get("M06").measures if m.measure == "CL12")
    assert note in cl12.notes
    classes, _ = size_classes(result.analysis.inputs, MeasureRequest())
    in_force = set(classes["threshold"].drop_nulls().to_list())
    assert in_force == set(comparison["cv08_threshold"].drop_nulls().to_list())  # CV08's only
    assert not in_force & set(ran["extreme_value_threshold"].to_list())  # MT18's never classes
    reasons = " ".join(result.analysis.get("M04").reasons)
    assert "MT11 bootstrap did not run" in reasons  # late columns paid nothing (record 0285)
    assert {"MT12", "MT13", "MT15", "MT16", "MT22"} <= {s["id"] for s in _manifest(result)["specs"]}
