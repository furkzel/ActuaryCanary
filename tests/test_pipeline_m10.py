"""M10 in a whole run: the profile is proposed, saved, reused, confirmed by editing its file, and
its SHA-256 is part of the run id and of the manifest (records 0421 and 0423). Written for the
test phase: a run of a generated scenario costs seconds, so these are slow."""

import json
from datetime import date

import polars as pl
import pytest

from actuarycanary.modules.runner import ModuleState
from actuarycanary.pipeline import run

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def manifest(result) -> dict:
    return json.loads(result.manifest.read_text(encoding="utf-8"))


def test_the_profile_is_proposed_saved_reused_and_confirmed_by_editing_its_file(
    scenario_folder, cache, tmp_path
) -> None:
    folder = scenario_folder("reinsurance_heavy")
    profiles = tmp_path / "profiles"
    first = run(folder, tmp_path / "a", cache_dir=cache, profiles_dir=profiles)
    record = manifest(first)["account_mapping"]
    assert record["status"] == "proposed" and record["confirmed_on"] is None
    saved = profiles / record["file"]
    assert saved.is_file() and record["file"].startswith("ledger-")
    assert first.analysis.get("M10").state in (ModuleState.RAN, ModuleState.LIMITED)
    names = {p.name for p in first.folder.iterdir()}
    assert {"reconciliation.csv", "unmapped_accounts.csv"} <= names
    rec = pl.read_csv(first.folder / "reconciliation.csv")
    assert set(rec["ledger_mapping"]) == {"proposed, not confirmed"} and rec["material"].sum() > 0

    again = run(folder, tmp_path / "b", cache_dir=cache, profiles_dir=profiles)
    assert again.run_id == first.run_id  # the saved file is read back and is the same

    saved.write_text(
        saved.read_text(encoding="utf-8").replace("confirmed_on: null", "confirmed_on: 2026-11-14"),
        encoding="utf-8",
    )
    confirmed = run(folder, tmp_path / "c", cache_dir=cache, profiles_dir=profiles)
    assert confirmed.run_id != first.run_id
    record = manifest(confirmed)["account_mapping"]
    assert (
        record["status"] == "confirmed" and record["confirmed_on"] == date(2026, 11, 14).isoformat()
    )
    rec = pl.read_csv(confirmed.folder / "reconciliation.csv")
    assert set(rec["ledger_mapping"]) == {"confirmed on 2026-11-14"}


def test_a_run_without_a_profiles_folder_uses_the_proposal_and_saves_nothing(
    scenario_folder, cache, tmp_path
) -> None:
    result = run(scenario_folder("reinsurance_heavy"), tmp_path / "out", cache_dir=cache)
    record = manifest(result)["account_mapping"]
    assert record["file"] is None and record["status"] == "proposed"
