"""The committed tiny spreadsheets: they validate against spec/data/ and match their truth.

These are reader tests: they open the spreadsheets under tests/fixtures/synthetic/ (read once
and cached as parquet keyed by SHA-256). The fixtures are refreshed with `just synth-fixtures`.
"""

from pathlib import Path

import polars as pl
import pytest

from actuarycanary.synthetic.check import check_folder, class_of
from actuarycanary.synthetic.check import read_feed as read_feed_or_none
from actuarycanary.synthetic.writer import sha256
from tests.synthetic.conftest import FIXTURES

pytestmark = pytest.mark.integration

SCENARIOS = ["baseline", "messy_headers"]
FEEDS = ["claim_valuations", "claims", "policies", "premiums", "expenses", "market"]

# the rule of spec/data/ that each injected fault breaks (extreme payments break none: they are
# outliers for the anomaly measures, not violations of a data rule)
FAULT_RULES = {
    "missing_currency": "DV-CLV-03",
    "unknown_status_labels": "DV-CLV-04",
    "duplicate_valuation_rows": "DV-CLV-06",
    "paid_to_date_decreasing_without_recovery": "DV-CLV-07",
    "report_before_occurrence": "DV-CLM-04",
    "duplicate_premium_rows": "DV-PRM-02",
}


def read_feed(folder: Path, feed: str) -> dict[str, pl.DataFrame]:
    sheets = read_feed_or_none(folder, feed)
    assert sheets is not None, f"{feed}.xlsx is missing"
    return sheets


def expected_violations(folder: Path) -> dict[str, int]:
    faults = pl.read_csv(folder / "truth" / "injected_faults.csv")
    counts = faults.group_by("fault_type").len()
    return {
        FAULT_RULES[r["fault_type"]]: r["len"]
        for r in counts.iter_rows(named=True)
        if r["fault_type"] in FAULT_RULES
    }


@pytest.fixture(scope="module", params=SCENARIOS)
def folder(request) -> Path:
    return FIXTURES / request.param


def test_the_six_spreadsheets_and_the_truth_are_there(folder):
    for feed in FEEDS:
        assert (folder / f"{feed}.xlsx").exists()
    truth = {p.name for p in (folder / "truth").iterdir()}
    assert {
        "ultimates.csv",
        "development_pattern.csv",
        "inflation.csv",
        "injected_faults.csv",
        "anomalies.csv",
    } <= truth


@pytest.mark.slow
def test_the_files_break_exactly_the_rules_of_the_injected_faults(folder):
    found = {}
    for violation in check_folder(folder):
        found[violation.rule] = found.get(violation.rule, 0) + violation.count
    assert found == expected_violations(folder)


def test_identifiers_survive_as_text_with_their_leading_zeros(folder):
    claims = read_feed(folder, "claims")["claims"]
    assert claims["claim_id"].dtype == pl.String and claims["claim_id"][0] == "00000001"
    policies = read_feed(folder, "policies")["policies"]
    assert policies["policy_id"][0] == "00000001"


def test_dates_are_dates_after_reading(folder):
    valuations = read_feed(folder, "claim_valuations")["claim_valuations"]
    assert valuations["valuation_date"].dtype == pl.Date
    assert read_feed(folder, "premiums")["premiums"]["booking_date"].dtype == pl.Date


def test_the_market_file_has_one_sheet_of_rates_and_one_of_the_index(folder):
    sheets = read_feed(folder, "market")
    assert set(sheets) == {"fx", "cpi"}
    assert set(sheets["cpi"]["kind"]) == {"PRICE_INDEX"} or folder.name == "messy_headers"
    assert sheets["cpi"].height == 120


@pytest.mark.parametrize("feed", FEEDS)
def test_reading_through_the_truth_gives_the_canonical_table(folder, feed):
    """Recognition test: layout undone with the recorded truth equals the clean table."""
    canonical = pl.read_parquet(folder / "canonical" / f"{feed}.parquet")
    sheets = read_feed(folder, feed)
    read = pl.concat(sheets.values())
    assert read.height == canonical.height
    for column in canonical.columns:
        if column in ("status", "segment", "channel", "type", "kind"):
            lookup = class_of(feed, column, read[column])
            expected = canonical[column]
            known = lookup.is_not_null()
            assert lookup.filter(known).to_list() == expected.filter(known).to_list()
        else:
            assert read[column].to_list() == canonical[column].to_list(), column


@pytest.mark.slow
def test_the_messy_files_have_title_rows_extra_columns_and_text_dates():
    folder = FIXTURES / "messy_headers"
    layout = pl.read_csv(folder / "truth" / "layout.csv")
    assert (layout["title_rows"] >= 1).any() and (
        layout["header_row"] == layout["title_rows"] + 1
    ).all()
    personal = pl.read_csv(folder / "truth" / "personal_data_columns.csv")
    assert set(personal["header"]) == {"SIGORTALI_ADI", "TCKN", "MUSTERI_NO"}
    assert set(personal["file"]) == {"claims", "policies"}
    for feed in ("claims", "policies"):
        assert not {"SIGORTALI_ADI", "TCKN", "MUSTERI_NO"} & set(
            read_feed(folder, feed)[feed].columns
        )
    formats = pl.read_csv(folder / "truth" / "date_formats.csv")
    assert formats.height > 5 and set(formats["text_format"]) <= {
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    }


def test_every_messy_header_is_recorded_with_the_field_it_stands_for():
    folder = FIXTURES / "messy_headers"
    mapping = pl.read_csv(folder / "truth" / "column_map.csv")
    valuations = mapping.filter(pl.col("file") == "claim_valuations")
    assert set(valuations["field"]) == {
        "claim_id", "valuation_date", "paid_to_date", "case_reserve", "status", "currency",
        "subrogation_to_date", "salvage_to_date", "expense_allocated_to_date",
        "ceded_paid_to_date", "ceded_reserve",
    }  # fmt: skip
    assert set(valuations["kind"]) <= {"canonical", "alias", "misspelt"}
    assert "misspelt" in set(mapping["kind"])


def test_the_manifest_hashes_match_the_committed_files(folder):
    import yaml

    manifest = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["scenario"] == folder.name and manifest["size"] == "tiny"
    for name, digest in manifest["sha256"].items():
        assert sha256(folder / name) == digest, name


def test_the_examples_are_the_same_spreadsheets_as_the_fixtures(folder):
    examples = FIXTURES.parents[2] / "examples" / folder.name
    for feed in FEEDS:
        assert sha256(examples / f"{feed}.xlsx") == sha256(folder / f"{feed}.xlsx")
