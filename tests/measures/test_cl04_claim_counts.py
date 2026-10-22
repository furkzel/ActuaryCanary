"""CL04 Claim counts by status: hand-computed fixtures of the specification."""

from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure, table
from tests.measures.shared import FEB29, MAR31
from tests.quality.builders import cv

STATUS_ROWS = [
    cv(1, claim_id="A", status="OPEN"),
    cv(2, claim_id="A", status="CLOSED"),
    cv(3, claim_id="A", status="CLOSED"),
    cv(1, claim_id="B", status="OPEN"),
    cv(2, claim_id="B", status="CLOSED"),
    cv(3, claim_id="B", status="REOPENED"),
    cv(2, claim_id="C", status="CLOSED_NIL"),
    cv(3, claim_id="C", status="CLOSED_NIL"),
    cv(1, claim_id="D", status="LITIGATED"),
    cv(2, claim_id="D", status="LITIGATED"),
    cv(3, claim_id="D", status="LITIGATED"),
    cv(1, claim_id="E", status="UNMAPPED"),
    cv(2, claim_id="E", status="UNMAPPED"),
    cv(3, claim_id="E", status="UNMAPPED"),
]


def test_cl04_stock_counts_at_each_month_end() -> None:
    result = measure(make_inputs({"claim_valuations": STATUS_ROWS}), "CL04", "valuation_date")
    counts = table(result)
    february = {
        t: counts[(FEB29, t)]
        for t in ("reported", "open", "closed", "nil_closed", "reopened", "litigated", "UNMAPPED")
    }
    assert february == {
        "reported": 5,
        "open": 1,
        "closed": 3,
        "nil_closed": 1,
        "reopened": 0,
        "litigated": 1,
        "UNMAPPED": 1,
    }
    march = {t: counts[(MAR31, t)] for t in february}
    assert march == {
        "reported": 5,
        "open": 2,
        "closed": 2,
        "nil_closed": 1,
        "reopened": 1,
        "litigated": 1,
        "UNMAPPED": 1,
    }


def test_cl04_flow_counts_newly_reported_closed_and_reopened_per_month() -> None:
    result = measure(
        make_inputs({"claim_valuations": STATUS_ROWS}),
        "CL04",
        "calendar_period",
        period=Period.MONTH,
    )
    counts = table(result)
    by_month = {
        month: {t: counts[(month, t)] for t in ("newly_reported", "closed", "reopened")}
        for month in ("2024-01", "2024-02", "2024-03")
    }
    assert by_month == {
        "2024-01": {"newly_reported": 4, "closed": 0, "reopened": 0},
        # C is reported already closed: it counts as newly reported and as closed
        "2024-02": {"newly_reported": 1, "closed": 3, "reopened": 0},
        "2024-03": {"newly_reported": 0, "closed": 0, "reopened": 1},
    }
