"""Injected faults land where they are listed and change nothing else."""

import polars as pl
import pytest

from actuarycanary.synthetic.faults import UNKNOWN_STATUS_LABELS
from tests.synthetic.conftest import simulate_with

NONE = {
    "injected_faults": {
        "duplicate_valuation_rows": 0,
        "report_before_occurrence": 0,
        "paid_to_date_decreasing_without_recovery": 0,
        "extreme_payment_outliers": 0,
        "missing_currency": 0,
        "unknown_status_labels": 0,
    }
}


def _faults(sim, kind):
    return [f for f in sim.faults if f.fault_type == kind]


def test_tiny_size_scales_every_fault_count_down_but_keeps_at_least_one(baseline):
    expected = {
        "duplicate_valuation_rows": 8,
        "report_before_occurrence": 4,
        "paid_to_date_decreasing_without_recovery": 3,
        "extreme_payment_outliers": 2,
        "missing_currency": 4,
        "unknown_status_labels": 2,
    }
    counts = {kind: len(_faults(baseline, kind)) for kind in expected}
    assert counts == expected


def test_no_faults_means_the_files_equal_the_clean_tables():
    sim = simulate_with(NONE)
    assert sim.faults == []
    assert sim.frames["claim_valuations"]["claim_valuations"].equals(sim.clean["claim_valuations"])
    assert sim.frames["claims"]["claims"].equals(sim.clean["claims"])


def test_report_before_occurrence_rows_have_a_report_date_before_the_occurrence_date(baseline):
    claims = baseline.frames["claims"]["claims"]
    for fault in _faults(baseline, "report_before_occurrence"):
        row = claims.row(fault.row, named=True)
        assert row["claim_id"] == fault.key and row["report_date"] < row["occurrence_date"]
    assert claims.filter(pl.col("report_date") < pl.col("occurrence_date")).height == 4


def test_decreasing_paid_rows_are_lower_than_the_row_before_and_have_no_recovery(baseline):
    rows = baseline.frames["claim_valuations"]["claim_valuations"]
    found = _faults(baseline, "paid_to_date_decreasing_without_recovery")
    assert found
    for fault in found:
        claim, month = fault.key.split("|")
        history = rows.filter(pl.col("claim_id") == claim).sort("valuation_date")
        at = history["valuation_date"].cast(pl.String).to_list().index(month)
        assert history["paid_to_date"][at] < history["paid_to_date"][at - 1]
        assert history["subrogation_to_date"][at] == 0 and history["salvage_to_date"][at] == 0


def test_extreme_payments_are_twenty_to_fifty_times_the_line_median(baseline):
    for fault in _faults(baseline, "extreme_payment_outliers"):
        added = float(fault.detail.split()[2])
        line = baseline.world.c_line[int(fault.key.split("|")[0]) - 1]
        positive = baseline.clean["claim_valuations"].with_columns(
            pl.col("paid_to_date").diff().over("claim_id").alias("step")
        )
        ids = baseline.clean["claims"].filter(pl.col("line") == line)["claim_id"]
        median = positive.filter(pl.col("claim_id").is_in(ids.implode()) & (pl.col("step") > 0))[
            "step"
        ].median()
        assert 20 <= added / median <= 50


def test_missing_currency_and_unknown_status_rows_are_marked_as_listed(baseline):
    rows = baseline.frames["claim_valuations"]["claim_valuations"]
    for fault in _faults(baseline, "missing_currency"):
        assert rows["currency"][fault.row] is None
    for fault in _faults(baseline, "unknown_status_labels"):
        assert rows["status"][fault.row] in UNKNOWN_STATUS_LABELS
    assert rows["currency"].null_count() == 4


def test_a_duplicate_row_is_an_exact_copy_of_the_row_above(baseline):
    rows = baseline.frames["claim_valuations"]["claim_valuations"]
    found = _faults(baseline, "duplicate_valuation_rows")
    assert found
    for fault in found:
        assert rows.row(fault.row) == rows.row(fault.row - 1)


def test_messy_scenario_adds_exact_duplicates_to_premiums_and_valuations():
    sim = simulate_with({"messiness": {"exact_duplicate_share": 0.02}})
    premiums = sim.frames["premiums"]["premiums"]
    assert len(_faults(sim, "duplicate_premium_rows")) == round(0.02 * sim.clean["premiums"].height)
    assert premiums.height - premiums.n_unique() == len(_faults(sim, "duplicate_premium_rows"))
    assert len(_faults(sim, "duplicate_valuation_rows")) > 8


@pytest.mark.parametrize("kind", ["missing_currency", "unknown_status_labels"])
def test_a_faulted_row_is_never_also_a_duplicate_of_another_fault(baseline, kind):
    duplicated = {f.key for f in _faults(baseline, "duplicate_valuation_rows")}
    assert not duplicated & {f.key for f in _faults(baseline, kind)}
