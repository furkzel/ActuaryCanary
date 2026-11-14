"""The scenario messy_incremental: messy_headers with claim amounts written per period (0374)."""

import hashlib
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.canonical.amounts import ACCUMULATED_FIELDS, INCREMENTAL, TO_DATE
from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.pipeline import recognise_folder
from actuarycanary.recognition.tables import canonical_table
from actuarycanary.spec.loader import load_specs
from actuarycanary.synthetic.build import synthesize
from actuarycanary.synthetic.messy import as_increments
from actuarycanary.synthetic.scenario import load_scenario
from tests.recognition.build import DICTIONARY

SPECS = load_specs()


def _read_valuations(folder: Path):
    loaded = [t for t in recognise_folder(folder, DICTIONARY, None, None)]
    items = [t for t in loaded if t.recognition.concept == "claim_valuations"]
    assert len(items) == 1
    item = items[0]
    raw, _ = canonical_table(item.table, item.recognition, DICTIONARY)
    amounts = item.recognition.amounts
    feed = canonicalise(raw, SPECS.data["claim_valuations"], amounts)
    return amounts, feed.frame


@pytest.fixture(scope="module")
def headers(scenario_folder):
    return scenario_folder("messy_headers")  # written once per session, shared (0420)


@pytest.fixture(scope="module")
def incremental(scenario_folder):
    return scenario_folder("messy_incremental")


@pytest.fixture(scope="module")
def read_headers(headers):
    return _read_valuations(headers)


@pytest.fixture(scope="module")
def read_incremental(incremental):
    return _read_valuations(incremental)


def _digests(folder: Path) -> dict[str, str]:
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != "manifest.yaml"
    }


def test_the_scenario_is_messy_headers_with_incremental_amounts():
    s = load_scenario("messy_incremental")
    assert s.messiness.amounts == "incremental"
    assert load_scenario("messy_headers").messiness.amounts == "to_date"
    assert s.messiness.headers == load_scenario("messy_headers").messiness.headers
    assert s.messiness.title_rows == load_scenario("messy_headers").messiness.title_rows


@pytest.mark.slow  # writes the scenario a second time
def test_generation_is_deterministic(incremental, tmp_path):
    synthesize("messy_incremental", "tiny", tmp_path)
    assert _digests(tmp_path) == _digests(incremental)


def test_only_the_claim_valuation_sheet_and_what_describes_it_differ_from_messy_headers(
    headers, incremental
):
    a, b = _digests(headers), _digests(incremental)
    assert a.keys() == b.keys()
    moved = {name for name in a if a[name] != b[name]}
    assert "claim_valuations.xlsx" in moved
    # the canonical parquet and the truth hold the cumulative amounts the reader must recover
    assert "canonical/claim_valuations.parquet" not in moved
    assert not {n for n in moved if n.startswith("truth/") and n != "truth/scenario.yaml"}
    assert moved == {"claim_valuations.xlsx", "truth/scenario.yaml"}


def test_the_existing_reader_detects_per_period_amounts(read_headers, read_incremental):
    kind_h, _ = read_headers
    kind_i, _ = read_incremental
    assert kind_h == TO_DATE and kind_i == INCREMENTAL


def test_the_reader_gives_the_canonical_claim_amounts_of_messy_headers(
    read_headers, read_incremental
):
    _, a = read_headers
    _, b = read_incremental
    assert a.height == b.height
    keys = ["claim_id", "valuation_date", "case_reserve"]
    fields = [f for f in ACCUMULATED_FIELDS if f in a.columns]
    a = a.select(*keys, *fields).sort(keys)
    b = b.select(*keys, *fields).sort(keys)
    for f in fields:
        x, y = a[f].fill_null(-1.0), b[f].fill_null(-1.0)
        assert (x - y).abs().max() < 0.005, f
    # the sheet itself does hold increments: paid falls after a payment in many rows
    assert b["paid_to_date"].max() == pytest.approx(a["paid_to_date"].max(), abs=0.01)


def test_as_increments_on_a_hand_made_table():
    frame = pl.DataFrame(
        {
            "claim_id": ["A", "A", "A", "A", "B", "B"],
            "valuation_date": ["2024-01-31", "2024-02-29", "2024-02-29", "2024-03-31"] * 1
            + ["2024-01-31", "2024-02-29"],
            "paid_to_date": [0.0, 100.0, 100.0, 250.5, None, 40.0],
            "case_reserve": [9.0, 8.0, 8.0, 0.0, 5.0, 5.0],
        }
    ).with_columns(pl.col("valuation_date").str.to_date())
    out = as_increments(frame)
    assert out["paid_to_date"].to_list() == [0.0, 100.0, 100.0, 150.5, None, 40.0]
    assert out["case_reserve"].to_list() == frame["case_reserve"].to_list()  # a stock
    assert out["claim_id"].to_list() == frame["claim_id"].to_list()  # row order kept
