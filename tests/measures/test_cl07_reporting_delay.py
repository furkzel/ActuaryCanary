"""CL07 Reporting delay: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import make_inputs, measure, one, table
from tests.quality.builders import claim, cv


def _delays(delays: list[int]):
    occurred = date(2024, 1, 10)
    claims = [
        claim(
            claim_id=f"K{i}",
            occurrence_date=occurred,
            report_date=date.fromordinal(occurred.toordinal() + d),
        )
        for i, d in enumerate(delays)
    ]
    rows = [cv(6, claim_id=f"K{i}") for i in range(len(delays))]
    return make_inputs({"claim_valuations": rows, "claims": claims})


def test_cl07_mean_and_median_with_a_negative_delay_excluded() -> None:
    result = measure(_delays([0, 2, 4, 10, -3]), "CL07", "origin_period")
    assert one(result) == 4.0
    assert one(result, "p50") == 3.0
    assert one(result, "n") == 4
    assert any("DV-CLM-04" in note for note in result.notes)  # the exclusion is counted


def test_cl07_percentiles_are_type_7_and_hidden_below_five_claims() -> None:
    few = measure(_delays([0, 2, 4, 10]), "CL07", "origin_period")
    assert one(few, "p90") is None and one(few, "p95") is None
    five = measure(_delays([0, 2, 4, 10, 20]), "CL07", "origin_period")
    assert one(five, "p50") == 4.0
    assert one(five, "p75") == 10.0
    assert one(five, "p90") == pytest.approx(16.0)  # 10 + 0.6 (20 - 10)
    assert one(five, "p95") == pytest.approx(18.0)


def test_cl07_recent_origin_periods_are_marked_incomplete() -> None:
    """Delays of 100 days in 2023 make a 2024 period that ended less than 100 days before the
    cut-off incomplete: long delays are not observed yet."""
    old, recent = date(2023, 1, 5), date(2024, 11, 20)
    claims = [
        claim(
            claim_id=f"K{i}",
            occurrence_date=old,
            report_date=date.fromordinal(old.toordinal() + 100),
        )
        for i in range(5)
    ] + [claim(claim_id=f"R{i}", occurrence_date=recent, report_date=recent) for i in range(5)]
    rows = [cv(12, claim_id=c["claim_id"]) for c in claims]
    result = measure(
        make_inputs({"claim_valuations": rows, "claims": claims}), "CL07", "origin_period"
    )
    assert table(result, "incomplete") == {("2023",): False, ("2024",): True}
