"""Where the generator writes each workbook (records 0242 and 0382): the feeds a run reads are
in the scenario folder, the interest rates and the life feeds in the subfolder `phase2/`."""

import pytest
import yaml

from actuarycanary.synthetic.check import check_folder
from actuarycanary.synthetic.writer import LATER_FOLDER, LATER_FOLDER_FEEDS

READ_BY_A_RUN = [
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
]


@pytest.mark.parametrize("scenario", ["baseline", "life_book", "messy_headers"])
def test_the_feeds_a_run_reads_are_in_the_scenario_folder(scenario, scenario_folder) -> None:
    folder = scenario_folder(scenario)
    here = {p.stem for p in folder.glob("*.xlsx")}
    apart = {p.stem for p in (folder / LATER_FOLDER).glob("*.xlsx")}
    assert here == set(READ_BY_A_RUN)
    life = {"life_in_force", "life_events", "fund_flows"} if scenario != "baseline" else set()
    assert apart == {"interest_rates"} | life
    assert apart <= set(LATER_FOLDER_FEEDS)
    manifest = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    assert "ledger.xlsx" in manifest["sha256"] and "phase2/ledger.xlsx" not in manifest["sha256"]
    assert "phase2/interest_rates.xlsx" in manifest["sha256"]


def test_the_checker_reads_the_feeds_from_both_places(scenario_folder) -> None:
    """The generated feeds break none of their rules, wherever their workbook is; a feed the
    checker could not find would be reported under the rule FILE."""
    violations = check_folder(scenario_folder("baseline"))
    assert all(v.rule != "FILE" for v in violations)
    later = ("DV-RTY", "DV-RTR", "DV-RCV", "DV-LDG", "DV-IRT")
    assert [v for v in violations if v.rule.startswith(later)] == []
