"""The examples refresh script copies every feed and confirms the demo's ledger profile (0811).
No generation: the folders are built in a temporary directory."""

from datetime import date
from pathlib import Path

from actuarycanary.ledger.profile import (
    AccountProfile,
    chart_fingerprint,
    read_profile,
    save_profile,
)
from docs.tools.refresh_examples import confirm_ledger_profiles, copy_feeds


def test_every_workbook_of_the_scenario_folder_is_copied(tmp_path: Path) -> None:
    source, target = tmp_path / "scenario", tmp_path / "example"
    (source / "phase2").mkdir(parents=True)
    wanted = ["claims.xlsx", "ledger.xlsx", "recoveries.xlsx", "premiums_part2.xlsx"]
    for name in wanted:
        (source / name).write_bytes(name.encode())
    (source / "manifest.yaml").write_text("x")
    (source / "canonical").mkdir()
    (source / "canonical" / "claims.parquet").write_bytes(b"x")
    (source / "phase2" / "interest_rates.xlsx").write_bytes(b"rates")
    (source / "phase2" / "fund_flows.xlsx").write_bytes(b"life")
    assert copy_feeds(source, target) == sorted(wanted)
    assert sorted(p.name for p in target.iterdir()) == sorted(wanted)
    assert copy_feeds(source, target, rates=True)[-1] == "interest_rates.xlsx"
    assert (target / "interest_rates.xlsx").read_bytes() == b"rates"
    assert not (target / "fund_flows.xlsx").exists()
    assert not (target / "manifest.yaml").exists()


def test_the_saved_ledger_profile_is_confirmed(tmp_path: Path) -> None:
    accounts = ["1000", "2000"]
    profile = AccountProfile(
        fingerprint=chart_fingerprint(accounts),
        accounts=accounts,
        rules=[],
    )
    assert profile.confirmed_on is None
    save_profile(tmp_path, profile)
    saved = confirm_ledger_profiles(tmp_path, date(2026, 11, 14))
    assert len(saved) == 1
    assert read_profile(saved[0])[0].confirmed_on == date(2026, 11, 14)
    assert confirm_ledger_profiles(tmp_path / "none", date(2026, 11, 14)) == []
