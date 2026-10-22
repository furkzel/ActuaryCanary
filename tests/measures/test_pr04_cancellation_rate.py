"""PR04 Cancellation rate: hand-computed fixtures of the specification."""

import pytest

from tests.measures.helpers import measure, one
from tests.measures.shared import BOOKED, premium_inputs, pt


def test_pr04_cancellation_rate() -> None:
    rows = [
        pt("T1", "WRITTEN", BOOKED, 1000.0),
        pt("T2", "ENDORSEMENT", BOOKED, 100.0),
        pt("T3", "CANCELLATION", BOOKED, -110.0),
        pt("T4", "REFUND", BOOKED, -55.0),
    ]
    result = measure(premium_inputs(rows), "PR04", "calendar_period")
    assert one(result) == pytest.approx(165 / 1100)


def test_pr04_nothing_written_is_not_computed() -> None:
    rows = [pt("T3", "CANCELLATION", BOOKED, -110.0)]
    result = measure(premium_inputs(rows), "PR04")
    assert one(result) is None and "zero or negative" in one(result, "note")
