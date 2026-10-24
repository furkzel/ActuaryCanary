"""Files written to disk: the first six feeds are untouched, the later feeds pass the data
checker against the specifications, the messy scenario is messy, a run ignores the later feeds."""

from pathlib import Path

import polars as pl
import pytest
import yaml
from typer.testing import CliRunner

from actuarycanary.synthetic.build import simulate, synthesize, write_outputs
from actuarycanary.synthetic.check import check_folder
from actuarycanary.synthetic.check_phase2 import severity_of
from actuarycanary.synthetic.phase2 import PHASE2_FEEDS, TRUTH_USERS
from actuarycanary.synthetic.scenario import load_with
from actuarycanary.synthetic.writer import sha256
from tests.synthetic.conftest import FIXTURES, NO_FAULTS

pytestmark = pytest.mark.slow

LATER_RULES = ("DV-RTY", "DV-RTR", "DV-RCV", "DV-LDG", "DV-IRT", "DV-LIF", "DV-LEV", "DV-FFL")


def _write(name: str, tmp_path: Path, overrides: dict | None = None) -> Path:
    out = tmp_path / name
    write_outputs(simulate(load_with(name, overrides or {}), "tiny"), out)
    return out


def _later(folder: Path) -> list:
    return [v for v in check_folder(folder, later_feeds=True) if v.rule.startswith(LATER_RULES)]


@pytest.mark.parametrize("scenario", ["baseline", "messy_headers"])
def test_every_file_of_version_one_tiny_is_byte_for_byte_what_it_was(scenario, tmp_path):
    frozen = yaml.safe_load((FIXTURES / "tiny_sha256_v1.yaml").read_text(encoding="utf-8"))[
        scenario
    ]
    out = tmp_path / scenario
    synthesize(scenario, "tiny", out)
    assert len(frozen) == 26
    changed = [name for name, digest in frozen.items() if sha256(out / name) != digest]
    assert changed == []


def test_the_same_seed_gives_the_same_bytes_for_every_file(tmp_path):
    synthesize("life_book", "tiny", tmp_path / "a")
    synthesize("life_book", "tiny", tmp_path / "b")
    first, second = (
        yaml.safe_load((tmp_path / name / "manifest.yaml").read_text(encoding="utf-8"))
        for name in ("a", "b")
    )
    assert first["sha256"] == second["sha256"]
    assert {
        "phase2/life_in_force.xlsx",
        "phase2/fund_flows.xlsx",
        "reference_tables/reference_mortality.csv",
    } <= set(first["sha256"])


def test_each_scenario_writes_its_feeds_the_logs_and_the_truth_files(tmp_path):
    out = _write("life_book", tmp_path, NO_FAULTS)
    for feed in PHASE2_FEEDS:
        assert (out / "phase2" / f"{feed}.xlsx").exists(), feed
        assert not (out / f"{feed}.xlsx").exists(), feed  # the six feeds are alone in the folder
        assert (out / "canonical" / f"{feed}.parquet").exists(), feed
    for name in TRUTH_USERS:
        assert (out / "truth" / f"{name}.csv").exists(), name
    assert (out / "truth" / "layout_phase2.csv").exists()
    assert (out / "truth" / "column_map_phase2.csv").exists()
    assert not any(
        row for row in pl.read_csv(out / "truth" / "layout.csv")["file"] if row.startswith("ledger")
    )
    dump = yaml.safe_load((out / "truth" / "scenario.yaml").read_text(encoding="utf-8"))
    assert "phase2" not in dump["scenario"]
    assert "truth_users" in (out / "truth" / "phase2_scenario.yaml").read_text(encoding="utf-8")
    money = pl.read_csv(out / "truth" / "money_columns_phase2.csv")
    assert {"file", "column", "currency", "conversion"} == set(money.columns)
    assert (out / "reference_tables" / "reference_lapse.csv").exists()


@pytest.mark.parametrize("scenario", ["baseline", "reinsurance_heavy", "life_book"])
def test_the_later_feeds_pass_the_data_checker(scenario, tmp_path):
    """Only what was written in on purpose is found: the ledger's missing row (a gap in the
    chain of balances, books out by that row) and its suspense account, outside the profile."""
    found = _later(_write(scenario, tmp_path, NO_FAULTS))
    blocking = [v for v in found if severity_of(v) == "BLOCKING"]
    assert blocking == []
    warnings = {(v.rule, v.count) for v in found if severity_of(v) == "WARNING"}
    assert warnings == {("DV-LDG-07", 1), ("DV-LDG-09", 1)}
    info = {v.rule for v in found if severity_of(v) == "INFO"}
    # a reversal of premium is negative, the books are out by the missing row, a curve follows
    # an inflation path that changes from year to year
    assert info <= {"DV-RTR-10", "DV-LDG-08", "DV-IRT-09"}


def test_the_messy_scenario_passes_the_checker_through_its_logs(tmp_path):
    """Turkish and English headers, text dates and translated labels of the later feeds are
    undone with the truth logs, and what is left is what was written in on purpose."""
    found = _later(_write("messy_headers", tmp_path, NO_FAULTS))
    assert [v for v in found if severity_of(v) == "BLOCKING"] == []
    warnings = {(v.rule, v.count) for v in found if severity_of(v) == "WARNING"}
    assert warnings == {("DV-LDG-07", 1), ("DV-LDG-09", 1)}


def test_the_messy_scenario_renames_the_headers_of_every_later_feed(tmp_path):
    out = _write("messy_headers", tmp_path, NO_FAULTS)
    columns = pl.read_csv(out / "truth" / "column_map_phase2.csv")
    assert set(columns["file"]) == set(PHASE2_FEEDS)
    for feed in PHASE2_FEEDS:
        kinds = set(columns.filter(pl.col("file") == feed)["kind"])
        assert "alias" in kinds or "misspelt" in kinds, feed
    assert (columns["header"] != columns["field"]).sum() > 40
    values = pl.read_csv(out / "truth" / "value_map_phase2.csv")
    assert values.height > 5 and set(values["file"]) <= set(PHASE2_FEEDS)
    layout = pl.read_csv(out / "truth" / "layout_phase2.csv")
    assert (layout["title_rows"] > 0).any()


def test_a_run_of_the_folder_ignores_the_later_feeds(tmp_path):
    """The workbooks of the later feeds are in a subfolder, so a run reads the folder as before:
    the run id equals that of a copy that holds the six workbooks only. (Beside the six they
    would be recognised as tables of the first six concepts and change the run.)"""
    from actuarycanary.cli import app

    out = _write("baseline", tmp_path, NO_FAULTS)
    six = tmp_path / "six"
    six.mkdir()
    for feed in ("claim_valuations", "claims", "policies", "premiums", "expenses", "market"):
        (six / f"{feed}.xlsx").write_bytes((out / f"{feed}.xlsx").read_bytes())
    ids = []
    for folder in (six, out):
        target = tmp_path / f"run_{folder.name}"
        result = CliRunner().invoke(app, ["run", str(folder), "--yes", "--out", str(target)])
        assert result.exit_code == 0, result.output
        ids.append(next(target.iterdir()).name)
    assert ids[0] == ids[1]


def test_the_command_writes_every_scenario_with_the_name_all(tmp_path):
    from actuarycanary.synthetic.__main__ import app
    from actuarycanary.synthetic.scenario import list_scenarios

    result = CliRunner().invoke(app, ["write", "all", "tiny", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    for name in list_scenarios():
        assert (tmp_path / name / "manifest.yaml").exists(), name
        assert (tmp_path / name / "phase2" / "ledger.xlsx").exists(), name
        assert (tmp_path / name / "truth" / "severity_truth.csv").exists(), name
