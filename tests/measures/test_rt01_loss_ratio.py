"""RT01 Loss ratio (paid, incurred, ultimate): hand-computed fixtures of the specification."""

from datetime import date

import polars as pl
import pytest

from actuarycanary.measures.port import NotAvailable
from tests.measures.helpers import measure, one, table
from tests.measures.shared import _loss_inputs, inputs_for, p
from tests.quality.builders import cv


def test_rt01_paid_incurred_and_ultimate_loss_ratios() -> None:
    inputs = _loss_inputs()
    for view, expected in (("paid", 0.40), ("incurred", 0.65), ("ultimate", 0.72)):
        result = measure(inputs, "RT01", "segment", "line", "origin_period", view=view)
        assert one(result) == pytest.approx(expected), view
    result = measure(inputs, "RT01", "origin_period")
    assert one(result, "paid_ratio") == pytest.approx(0.4)
    assert one(result, "incurred_ratio") == pytest.approx(0.65)
    assert one(result, "ultimate_ratio") == pytest.approx(0.72)


def test_rt01_calendar_view_is_the_incurred_movement_over_the_earned_premium_of_the_period() -> (
    None
):
    result = measure(_loss_inputs(), "RT01", "calendar_period")
    assert one(result) == pytest.approx(0.65)


def test_rt01_paid_and_incurred_are_shown_when_the_ultimate_is_not_available() -> None:
    inputs = _loss_inputs(ultimate=NotAvailable("selection failed"))
    result = measure(inputs, "RT01", "origin_period")
    assert one(result) == pytest.approx(0.65)
    assert "ultimate_ratio" not in result.frame.columns  # type: ignore[union-attr]
    assert any("selection failed" in n for n in result.notes)
    assert measure(inputs, "RT01", "origin_period", view="ultimate").reason.startswith(
        "the ultimate ratio"
    )


def test_rt01_without_claims_only_the_all_business_calendar_view_exists() -> None:
    inputs = inputs_for([p("WRITTEN", 1000.0)])
    assert measure(inputs, "RT01", "segment").reason.startswith("claims are not loaded")
    result = measure(inputs, "RT01", "calendar_period")
    assert result.available and "segments not separated" in result.notes


def test_rt01_earned_premium_zero_is_not_computed() -> None:
    inputs = inputs_for([p("WRITTEN", 0.0)], claims_rows=[cv(12, claim_id="K0")])
    assert one(measure(inputs, "RT01", "calendar_period"), "note").startswith(
        "earned premium is zero"
    )


def test_rt01_a_period_before_the_claims_data_is_missing_not_a_zero_ratio() -> None:
    """Premium is earned in 2023 too, but the claims start in 2024: no 2023 ratio is shown."""
    inputs = _loss_inputs()
    earlier = inputs.feeds["policies"].with_columns(pl.lit(date(2023, 1, 1)).alias("start_date"))
    premiums = inputs.feeds["premiums"].with_columns(pl.lit(date(2023, 1, 1)).alias("booking_date"))
    inputs.feeds = {**inputs.feeds, "policies": earlier, "premiums": premiums}  # type: ignore[misc]
    result = measure(inputs, "RT01", "origin_period")
    assert [k[0] for k in table(result)] == ["2024"]
