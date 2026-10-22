"""CL06 Average claim severity: hand-computed fixtures of the specification."""

from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure, one, table
from tests.quality.builders import claim, cv


def _severity_inputs():
    """One origin, six claims: incurred 10, 20, 30, 0 (nil-closed), 40 and 500 (LARGE by a
    fixed threshold of 100)."""
    sizes = [10.0, 20.0, 30.0, 0.0, 40.0, 500.0]
    rows = [
        cv(
            1,
            claim_id=f"K{i}",
            paid_to_date=size,
            case_reserve=0.0,
            status="CLOSED_NIL" if size == 0.0 else "CLOSED",
        )
        for i, size in enumerate(sizes)
    ]
    claims = [claim(claim_id=f"K{i}", segment="S", line="L") for i in range(len(sizes))]
    return make_inputs(
        {"claim_valuations": rows, "claims": claims},
        large_loss_thresholds={("S", "L"): 100.0},
    )


def test_cl06_severity_by_size_class_and_all() -> None:
    result = measure(_severity_inputs(), "CL06", "origin_period", "claim_size_class")
    assert table(result) == {
        ("2024", "ATTRITIONAL"): 25.0,  # (10 + 20 + 30 + 0 + 40) / 4 non-nil claims
        ("2024", "LARGE"): 500.0,
        ("2024", "all"): 120.0,  # 600 / 5
    }


def test_cl06_nil_claims_count_when_exclude_nil_is_false() -> None:
    result = measure(_severity_inputs(), "CL06", "origin_period", params=(("exclude_nil", False),))
    assert one(result) == 100.0  # 600 / 6


def test_cl06_without_claims_all_claims_form_one_unknown_group_on_the_first_valuation_month() -> (
    None
):
    rows = [
        cv(1, claim_id="A", paid_to_date=10.0, case_reserve=0.0),
        cv(2, claim_id="B", paid_to_date=30.0, case_reserve=0.0),
    ]
    result = measure(
        make_inputs({"claim_valuations": rows}),
        "CL06",
        "segment",
        "origin_period",
        period=Period.MONTH,
    )
    assert table(result) == {("UNKNOWN", "2024-01"): 10.0, ("UNKNOWN", "2024-02"): 30.0}
    assert any("proxy" in note for note in result.notes)


def test_cl06_group_without_non_nil_claims_is_not_computed() -> None:
    rows = [cv(1, paid_to_date=0.0, case_reserve=0.0, status="CLOSED_NIL")]
    result = measure(make_inputs({"claim_valuations": rows}), "CL06")
    assert one(result) is None
    assert "non-nil" in one(result, "note")
