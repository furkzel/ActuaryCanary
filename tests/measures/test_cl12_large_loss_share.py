"""CL12 Large-loss share: hand-computed fixtures of the specification."""

import pytest

from tests.measures.helpers import make_inputs, measure, one
from tests.quality.builders import claim, cv


def test_cl12_large_loss_share_with_components() -> None:
    """Incurred 10, 20, 30, 140; 140 is LARGE (threshold 100) and the claim with 30 has an event
    code: (140 + 30) / 200 = 0.85, with components 0.70 and 0.15."""
    sizes = [10.0, 20.0, 30.0, 140.0]
    rows = [cv(1, claim_id=f"K{i}", paid_to_date=s, case_reserve=0.0) for i, s in enumerate(sizes)]
    claims = [
        claim(claim_id=f"K{i}", segment="S", line="L", event_code="STORM" if i == 2 else None)
        for i in range(4)
    ]
    inputs = make_inputs(
        {"claim_valuations": rows, "claims": claims}, large_loss_thresholds={("S", "L"): 100.0}
    )
    result = measure(inputs, "CL12", "origin_period")
    assert one(result) == pytest.approx(0.85)
    assert one(result, "large_share") == pytest.approx(0.70)
    assert one(result, "catastrophe_share") == pytest.approx(0.15)


def test_cl12_group_without_a_large_class_is_not_computed_with_the_cv08_reason() -> None:
    rows = [
        cv(1, claim_id=f"K{i}", paid_to_date=10.0 * (i + 1), case_reserve=0.0) for i in range(4)
    ]
    result = measure(
        make_inputs({"claim_valuations": rows}), "CL12"
    )  # 4 claims < 100: no percentile
    assert one(result) is None
    assert "CV08" in one(result, "note")


def test_cl12_shows_the_mt18_threshold_in_its_notes_and_still_classes_by_cv08() -> None:
    """Record 0601: the extreme-value threshold of MT18 is reported beside CV08's, never used."""
    sizes = [10.0, 20.0, 30.0, 140.0]
    rows = [cv(1, claim_id=f"K{i}", paid_to_date=s, case_reserve=0.0) for i, s in enumerate(sizes)]
    note = "MT18 extreme-value threshold beside the CV08 large-loss threshold: S / L 15 against 100"
    claims = [claim(claim_id=f"K{i}", segment="S", line="L") for i in range(4)]
    feeds = {"claim_valuations": rows, "claims": claims}
    kept = make_inputs(feeds, large_loss_thresholds={("S", "L"): 100.0})
    shown = make_inputs(
        feeds,
        large_loss_thresholds={("S", "L"): 100.0},
        extreme_value_note=note,
    )
    result, plain = measure(shown, "CL12", "origin_period"), measure(kept, "CL12", "origin_period")
    assert note in result.notes and note not in plain.notes
    assert one(result) == one(plain) == pytest.approx(140 / 200)  # only 140 is above CV08's 100
