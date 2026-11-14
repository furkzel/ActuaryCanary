"""The committed examples are what the generator and the pipeline give today (slow: each test
generates or runs the demo, about half a minute)."""

import json
import shutil
from pathlib import Path

import pytest

from actuarycanary.cli.demo import DEMO_CURVE
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.pipeline import RunSettings, run
from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.build import synthesize
from actuarycanary.synthetic.writer import sha256

ROOT = find_spec_root().parent
FEEDS = [
    "claim_valuations",
    "claims",
    "policies",
    "premiums",
    "expenses",
    "market",
    "reinsurance_treaties",
    "reinsurance_transactions",
    "recoveries",
    "ledger",
]  # the six feeds and the four of records 0382 and 0811

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def test_the_demo_files_are_what_the_scenario_writes_today(tmp_path: Path) -> None:
    synthesize("demo", "demo", tmp_path)
    for feed in FEEDS:
        committed = ROOT / "examples" / "demo" / f"{feed}.xlsx"
        assert sha256(committed) == sha256(tmp_path / f"{feed}.xlsx"), (
            f"{feed}.xlsx differs: run `just examples` and commit the result"
        )
    # the interest rates of the scenario, which the demo ships for the discounted basis (0346)
    rates = ROOT / "examples" / "demo" / "interest_rates.xlsx"
    assert sha256(rates) == sha256(tmp_path / "phase2" / "interest_rates.xlsx")


@pytest.mark.parametrize("example", ["baseline", "messy_headers", "demo"])
def test_running_an_example_gives_the_run_id_of_its_committed_report(
    example: str, tmp_path: Path
) -> None:
    curve = DEMO_CURVE if example == "demo" else None  # as `canary demo` runs it (0346)
    settings = RunSettings(discount=DiscountSettings(curve_id=curve))
    profiles = tmp_path / "profiles"
    for shipped in (ROOT / "examples" / example / "report").glob("ledger-*.yaml"):
        profiles.mkdir(exist_ok=True)  # the confirmed profile the committed run used (0811)
        shutil.copy(shipped, profiles / shipped.name)
    result = run(ROOT / "examples" / example, tmp_path / "out", settings, profiles_dir=profiles)
    manifest = json.loads(
        (ROOT / "examples" / example / "report" / "manifest.json").read_text(encoding="utf-8")
    )
    assert result.run_id == manifest["run_id"], "run `just examples` and read the diff"
