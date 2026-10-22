"""CL08 Settlement time: hand-computed fixtures of the specification."""

from datetime import date

import pytest

from tests.measures.helpers import make_inputs, measure, one
from tests.quality.builders import claim, cv


def test_cl08_mean_of_closed_claims_and_the_product_limit_curve() -> None:
    """All claims are reported on 2024-01-01 and the cut-off is 2024-06-30. C1 closes after 10
    days, C2 and C3 after 20, C4 has no close date and closes in February (derived, 59 days);
    two claims stay open (181 days, censored). At risk 6, 5, 3: S = 5/6, 1/2, 1/3."""
    report = date(2024, 1, 1)
    closed_on = {
        "C1": date(2024, 1, 11),
        "C2": date(2024, 1, 21),
        "C3": date(2024, 1, 21),
        "C4": None,
    }
    claims = [
        claim(claim_id=name, report_date=report, close_date=close)
        for name, close in closed_on.items()
    ] + [claim(claim_id=name, report_date=report, close_date=None) for name in ("O1", "O2")]
    rows = []
    for name in closed_on:
        rows.append(cv(1, claim_id=name, status="OPEN"))
        rows.append(cv(2 if name == "C4" else 1, claim_id=name, status="CLOSED"))
        rows.append(cv(6, claim_id=name, status="CLOSED"))
    rows += [cv(1, claim_id=name, status="OPEN") for name in ("O1", "O2")]
    rows += [cv(6, claim_id=name, status="OPEN") for name in ("O1", "O2")]
    result = measure(make_inputs({"claim_valuations": rows, "claims": claims}), "CL08")
    assert one(result) == pytest.approx((10 + 20 + 20 + 59) / 4)
    assert one(result, "closed") == 4 and one(result, "open") == 2
    assert one(result, "p50") == 20.0
    assert one(result, "p75") is None  # the curve stays above 0.25: beyond the observed range
    survival = result.tables["survival"]
    assert survival["duration_days"].to_list() == [10, 20, 59]
    assert survival["survival"].to_list() == pytest.approx([5 / 6, 1 / 2, 1 / 3])
    assert any("derived" in note for note in result.notes)


def test_cl08_reopened_and_closed_again_counts_its_last_closing() -> None:
    claims = [claim(claim_id="A", report_date=date(2024, 1, 1), close_date=None)]
    statuses = ["CLOSED", "REOPENED", "CLOSED"]
    rows = [cv(m, claim_id="A", status=s) for m, s in zip((1, 2, 3), statuses, strict=True)]
    result = measure(make_inputs({"claim_valuations": rows, "claims": claims}), "CL08")
    assert one(result) == 90.0  # 2024-01-01 to 2024-03-31
