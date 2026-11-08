"""MT19 called from M03 in a run (record 0341): its files, settings, diagnostics, register
entries and notes reach the manifest, and the module lists the method."""

import json

import polars as pl
import pytest

from actuarycanary.modules import survival_run
from actuarycanary.pipeline import RunResult

pytestmark = pytest.mark.integration


def test_the_run_writes_the_survival_files_and_lists_them(default_run: RunResult) -> None:
    manifest = json.loads(default_run.manifest.read_text(encoding="utf-8"))
    names = {o["name"] for o in manifest["outputs"]}
    assert set(survival_run.TABLES.values()) <= names
    groups = pl.read_csv(default_run.folder / "survival_groups.csv")
    assert groups.height and set(groups["segment"]) == {"LIFE", "NON_LIFE"}
    assert {"MT19"} <= {s["id"] for s in manifest["specs"]}
    assert next(s for s in manifest["specs"] if s["id"] == "MT19")["version"] == "1.1.0"
    assert manifest["settings"]["survival"] == survival_run.settings()


def test_m03_lists_mt19_and_takes_its_notes(default_run: RunResult) -> None:
    outcome = default_run.analysis.get("M03")
    assert "MT19" in outcome.methods_built and not outcome.methods_missing
    notes = default_run.survival.notes["M03"]
    assert all(n in outcome.reasons for n in notes)


def test_the_diagnostics_and_the_register_entries_of_mt19_are_written(
    default_run: RunResult,
) -> None:
    diagnostics = pl.read_csv(default_run.folder / "diagnostics.csv")
    assert diagnostics.filter(pl.col("method") == "MT19").height == len(
        default_run.survival.diagnostics
    )
    assumptions = pl.read_csv(default_run.folder / "assumptions.csv")
    assert assumptions.filter(pl.col("method") == "MT19").height == len(
        default_run.survival.entries
    )
