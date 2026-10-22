"""CL09 Settlement rate: hand-computed fixtures of the specification."""

import pytest

from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure, table, values
from tests.quality.builders import cv


def test_cl09_settlement_rate_is_closings_over_open_at_start_plus_new() -> None:
    """Ten open at the start of February, five reported in February, six closings: 6 / 15."""
    rows = [cv(1, claim_id=f"O{i}", status="OPEN") for i in range(10)]
    rows += [cv(2, claim_id=f"O{i}", status="CLOSED" if i < 6 else "OPEN") for i in range(10)]
    rows += [cv(2, claim_id=f"N{i}", status="OPEN") for i in range(5)]
    result = measure(
        make_inputs({"claim_valuations": rows}), "CL09", "calendar_period", period=Period.MONTH
    )
    assert table(result)[("2024-02",)] == pytest.approx(0.4)
    assert table(result)[("2024-01",)] is None  # the open count at the start is unknown
    assert "first period" in values(result, "note")[0]


def test_cl09_denominator_zero_is_not_computed() -> None:
    rows = [cv(1, claim_id="A", status="CLOSED"), cv(2, claim_id="A", status="CLOSED")]
    result = measure(
        make_inputs({"claim_valuations": rows}), "CL09", "calendar_period", period=Period.MONTH
    )
    assert table(result)[("2024-02",)] is None
    assert values(result, "note")[1] == "no open or new claims: not computed"
