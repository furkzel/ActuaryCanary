"""The four feeds of the generated scenarios through recognition, mapping, the canonical rules
and the data rules (F1bc stage 5): the messy layouts give the clean canonical data, and every
fault the generator wrote into the four feeds is found with the count of the truth."""

from functools import cache
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.canonical.recoveries import build_recoveries, recovery_differences
from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.synthetic.check import check_folder

NEW = ("reinsurance_treaties", "reinsurance_transactions", "recoveries", "ledger")
RULES = ("DV-RTY", "DV-RTR", "DV-RCV", "DV-LDG")
MESSY = ("messy_headers", "messy_incremental")
# what the platform finds beyond the generator's checker, or cannot evaluate yet (record 0384)
PREMIUM_BEFORE_INCEPTION = "DV-RTR-06"  # the checker implements the claim half only
NEEDS_THE_PROFILE = "DV-LDG-09"  # the account-mapping profile (CV12) is not built


def _counts(report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in report.findings:
        if f.rule.startswith(RULES):
            counts[f.rule] = counts.get(f.rule, 0) + f.count
    return counts


@cache
def _checked_truth(folder: Path) -> tuple[tuple[str, int], ...]:
    return tuple(
        (v.rule, v.count)
        for v in check_folder(folder, later_feeds=True)
        if v.rule.startswith(RULES)
    )


def _truth(folder: Path) -> dict[str, int]:
    """Counts of the generator's checker for the rules of the four feeds."""
    return dict(_checked_truth(folder))


@pytest.fixture(scope="module", params=["baseline", "reinsurance_heavy"])
def clean(request, scenario_folder, scenario_checked):
    folder = scenario_folder(request.param)
    feeds, report = scenario_checked(request.param)
    _checked_truth(folder)  # the checker of the generator runs here, not in the first test
    return request.param, folder, feeds, report


@pytest.fixture(scope="module", params=MESSY)
def messy(request, scenario_folder, scenario_checked):
    """A messy scenario, mapped and checked once for all the tests of this module (the cost
    falls into the fixture, not into the first test that asks for it)."""
    folder = scenario_folder(request.param)
    feeds, report = scenario_checked(request.param)
    return request.param, folder, feeds, report


@pytest.fixture(scope="module")
def life_book_report(scenario_checked):
    return scenario_checked("life_book")[1]


# --- the messy layouts map to the clean canonical data ------------------------------------


@pytest.mark.parametrize("concept", NEW)
def test_a_messy_feed_maps_to_the_canonical_data_of_the_generator(concept, messy) -> None:
    scenario, folder, feeds, _ = messy
    expected = pl.read_parquet(folder / "canonical" / f"{concept}.parquet")
    got = feeds[concept].frame.drop(SOURCE_COLUMNS)
    # the ledger header CERDIT is one swapped letter in six: too short for the fuzzy layer, so
    # the column waits for the user (record 0390, tests/recognition/test_new_feeds.py)
    unmapped = {"credit"} if concept == "ledger" else set()
    assert set(expected.columns) - set(got.columns) == unmapped, concept
    expected = expected.drop(unmapped)
    got = got.select(expected.columns)
    assert got.schema == expected.schema, concept
    keys = [c for c in expected.columns if expected.schema[c] != pl.Float64]
    assert got.sort(keys).equals(expected.sort(keys)), concept


def test_the_messy_scenarios_have_the_findings_of_their_clean_scenario(
    messy, life_book_report
) -> None:
    """messy_headers and messy_incremental start from life_book: other headers, labels, date
    texts and title rows, the same data and so the same findings."""
    assert _counts(messy[3]) == _counts(life_book_report)


# --- every fault of the truth is found with its count ---------------------------------------


def test_the_data_rules_agree_with_the_checker_of_the_generator(clean) -> None:
    name, folder, _, report = clean
    found, truth = _counts(report), _truth(folder)
    found.pop(PREMIUM_BEFORE_INCEPTION, None)
    truth.pop(NEEDS_THE_PROFILE, None)
    assert found == truth, name
    assert found  # the scenarios are not free of faults


def test_fault_missing_ledger_row_shows_as_a_broken_opening_balance(clean) -> None:
    """Truth kind `missing_row`: one account-month is left out; the row after it opens with a
    balance that is not the closing balance of the row before (DV-LDG-07)."""
    _, folder, _, report = clean
    truth = pl.read_csv(folder / "truth" / "ledger_differences.csv")
    missing = truth.filter(pl.col("kind") == "missing_row").height
    assert missing >= 1 and _counts(report).get("DV-LDG-07", 0) == missing


def test_fault_books_that_do_not_balance(clean) -> None:
    """DV-LDG-08: the entity-months whose closing balances do not sum to zero."""
    _, folder, feeds, report = clean
    ledger = pl.read_parquet(folder / "canonical" / "ledger.parquet")
    sums = ledger.group_by("entity", "period", "currency").agg(pl.col("closing_balance").sum())
    off = sums.filter(pl.col("closing_balance").abs() > 0.05).height
    assert off >= 1 and _counts(report)["DV-LDG-08"] == off
    finding = next(f for f in report.findings if f.rule == "DV-LDG-08")
    assert finding.severity == "INFO" and "do not sum to zero" in finding.message


def test_fault_unmapped_account_waits_for_the_mapping_profile(clean) -> None:
    """Truth kind `unmapped_account` is what DV-LDG-09 lists; it needs the profile of CV12."""
    _, folder, _, report = clean
    truth = pl.read_csv(folder / "truth" / "ledger_differences.csv")
    assert truth.filter(pl.col("kind") == "unmapped_account").height >= 1
    assert "DV-LDG-09" not in _counts(report)
    assert "CV12" in dict(report.not_evaluated)["DV-LDG-09"]


def test_fault_reversed_ceded_movements_are_listed_as_information(clean) -> None:
    """DV-RTR-10: premium, commission and paid movements that are not positive (reversals)."""
    _, folder, _, report = clean
    moves = pl.read_parquet(folder / "canonical" / "reinsurance_transactions.parquet")
    reversals = moves.filter(
        (pl.col("type") != "CEDED_CASE_RESERVE") & (pl.col("amount") <= 0)
    ).height
    assert reversals >= 1 and _counts(report)["DV-RTR-10"] == reversals


def test_fault_ceded_above_gross_and_disagreeing_ceded_fields(scenario_folder, scenario_checked):
    """reinsurance_heavy: one valuation where the ceded movements exceed the gross amount
    (DV-RTR-08) and one where they differ from the ceded fields of the valuation (DV-RTR-09)."""
    truth = _truth(scenario_folder("reinsurance_heavy"))
    found = _counts(scenario_checked("reinsurance_heavy")[1])
    assert truth["DV-RTR-08"] == found["DV-RTR-08"] == 1
    assert truth["DV-RTR-09"] == found["DV-RTR-09"] == 1
    assert "DV-RTR-08" not in _counts(scenario_checked("baseline")[1])


def test_premium_movements_before_the_first_treaty_period_are_listed(clean) -> None:
    """Beyond the generator's checker (record 0384): the movements of the year before the first
    contract period in the treaties file fail the premium half of DV-RTR-06."""
    _, folder, feeds, report = clean
    moves = feeds["reinsurance_transactions"].frame
    first = (
        feeds["reinsurance_treaties"]
        .frame.group_by("treaty_id")
        .agg(pl.col("inception_date").min().alias("first"))
    )
    early = moves.join(first, on="treaty_id").filter(
        pl.col("type").is_in(["CEDED_PREMIUM", "REINSTATEMENT_PREMIUM"])
        & (pl.col("booking_date") < pl.col("first"))
    )
    assert early.height > 0 and _counts(report)["DV-RTR-06"] == early.height


def test_recoveries_agree_with_the_truth_and_with_the_to_date_fields(clean) -> None:
    """The recoveries truth: every recovery booked by the cut-off is a transaction, the
    transactions add up to the to-date fields (DV-RCV-08 lists nothing), and deriving the flows
    from the to-date fields gives the same totals per claim and type."""
    _, folder, feeds, report = clean
    truth = pl.read_csv(folder / "truth" / "recoveries_truth.csv", try_parse_dates=True)
    booked = truth.filter(pl.col("booked_by_cutoff"))
    recoveries, valuations = feeds["recoveries"].frame, feeds["claim_valuations"].frame
    assert recoveries.height == booked.height
    assert abs(recoveries["amount"].sum() - booked["recovery_amount"].sum()) < 0.005
    assert not [r for r in _counts(report) if r.startswith("DV-RCV")]
    assert recovery_differences(recoveries, valuations).height == 0
    derived = build_recoveries(None, valuations).frame
    by = ["claim_id", "type"]
    totals = derived.group_by(by).agg(pl.col("amount").sum().round(2)).sort(by)
    expected = recoveries.group_by(by).agg(pl.col("amount").sum().round(2)).sort(by)
    assert totals.equals(expected)
