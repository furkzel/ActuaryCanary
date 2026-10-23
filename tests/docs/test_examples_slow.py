"""The committed examples are what the generator and the pipeline give today (slow: each test
generates or runs the demo, about half a minute)."""

import json
from pathlib import Path

import pytest

from actuarycanary.pipeline import run
from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.build import synthesize
from actuarycanary.synthetic.writer import sha256

ROOT = find_spec_root().parent
FEEDS = ["claim_valuations", "claims", "policies", "premiums", "expenses", "market"]

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def test_the_demo_files_are_what_the_scenario_writes_today(tmp_path: Path) -> None:
    synthesize("demo", "demo", tmp_path)
    for feed in FEEDS:
        committed = ROOT / "examples" / "demo" / f"{feed}.xlsx"
        assert sha256(committed) == sha256(tmp_path / f"{feed}.xlsx"), (
            f"{feed}.xlsx differs: run `just examples` and commit the result"
        )


@pytest.mark.parametrize("example", ["baseline", "messy_headers", "demo"])
def test_running_an_example_gives_the_run_id_of_its_committed_report(
    example: str, tmp_path: Path
) -> None:
    result = run(ROOT / "examples" / example, tmp_path / "out", profiles_dir=tmp_path / "profiles")
    manifest = json.loads(
        (ROOT / "examples" / example / "report" / "manifest.json").read_text(encoding="utf-8")
    )
    assert result.run_id == manifest["run_id"], "run `just examples` and read the diff"
