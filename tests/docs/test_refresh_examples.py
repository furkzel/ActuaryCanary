"""The examples refresh script copies every feed and confirms the demo's ledger profile (0811).
No generation: the folders are built in a temporary directory."""

import shutil
from datetime import date
from pathlib import Path

import pytest

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


# --- the profile of an example is never rewritten (record 0816) ------------------------------


class _Result:
    def __init__(self, run_id: str, report: Path) -> None:
        self.run_id, self.report = run_id, report


def _fake_run(calls: list[Path]):
    """A run that proposes a profile when the folder has none, and whose id is the hash of the
    profile it read: what the real run does with the profile hash in the run id."""
    import hashlib

    def run(folder: Path, out: Path, settings, profiles_dir: Path) -> _Result:
        calls.append(folder)
        saved = sorted(profiles_dir.glob("ledger-*.yaml")) if profiles_dir.is_dir() else []
        if not saved:
            accounts = ["1000"]
            profile = AccountProfile(
                fingerprint=chart_fingerprint(accounts), accounts=accounts, rules=[]
            )
            saved = [save_profile(profiles_dir, profile)]
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.html").write_text("report", encoding="utf-8")
        (out / "manifest.json").write_text("{}", encoding="utf-8")
        return _Result(hashlib.sha256(saved[0].read_bytes()).hexdigest()[:16], out / "report.html")

    return run


def test_a_shipped_profile_is_copied_unchanged_and_never_confirmed_again(
    tmp_path: Path, monkeypatch
) -> None:
    from docs.tools import refresh_examples

    examples = tmp_path / "examples"
    (examples / "demo" / "report").mkdir(parents=True)
    accounts = ["1000", "2000"]
    shipped = save_profile(
        examples / "demo" / "report",
        AccountProfile(
            fingerprint=chart_fingerprint(accounts),
            accounts=accounts,
            rules=[],
            confirmed_on=date(2026, 11, 14),
        ),
    )
    before = shipped.read_bytes()
    calls: list[Path] = []
    monkeypatch.setattr(refresh_examples, "run", _fake_run(calls))
    ids = refresh_examples.write_reports(examples, today=date(2031, 1, 1))
    assert shipped.read_bytes() == before  # the confirmation date is still 2026-11-14
    assert len(calls) == 1  # one run: nothing was confirmed, so nothing is run again
    assert ids["demo"] == __import__("hashlib").sha256(before).hexdigest()[:16]
    assert sorted(p.name for p in (examples / "demo" / "report").iterdir()) == sorted(
        ["report.html", "manifest.json", shipped.name]
    )


def test_an_example_without_a_profile_gets_one_confirmed_today(tmp_path: Path, monkeypatch) -> None:
    from docs.tools import refresh_examples

    examples = tmp_path / "examples"
    (examples / "demo").mkdir(parents=True)
    calls: list[Path] = []
    monkeypatch.setattr(refresh_examples, "run", _fake_run(calls))
    refresh_examples.write_reports(examples, today=date(2031, 1, 1))
    assert len(calls) == 2  # proposed first, then run again on the confirmed profile
    (saved,) = (examples / "demo" / "report").glob("ledger-*.yaml")
    assert read_profile(saved)[0].confirmed_on == date(2031, 1, 1)


@pytest.mark.slow
def test_a_reports_only_refresh_of_the_demo_keeps_its_profile_and_gives_the_run_id_of_a_plain_run(
    tmp_path: Path,
) -> None:
    """On a copy of the demo folder (two runs of the demo, about 40 seconds)."""
    from actuarycanary.cli.demo import DEMO_CURVE, find_demo_folder
    from actuarycanary.convert.discount import DiscountSettings
    from actuarycanary.pipeline import RunSettings, run
    from docs.tools.refresh_examples import write_reports

    folder = tmp_path / "examples" / "demo"
    shutil.copytree(find_demo_folder(), folder)
    (profile,) = (folder / "report").glob("ledger-*.yaml")
    before = profile.read_bytes()
    ids = write_reports(tmp_path / "examples", today=date(2031, 1, 1))
    assert profile.read_bytes() == before
    settings = RunSettings(discount=DiscountSettings(curve_id=DEMO_CURVE))
    plain = run(folder, tmp_path / "plain", settings, profiles_dir=folder / "report")
    assert ids["demo"] == plain.run_id
