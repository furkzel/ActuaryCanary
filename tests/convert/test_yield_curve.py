"""Yield curves for discounting (CV10): zero rates from each rate type, the par bootstrap, the
interpolation of the negative log discount factor, the flat last forward rate, DV-IRT-09.

Every expected value is a closed form or computed by hand in the test."""

from datetime import date
from typing import Any

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.yield_curve import (
    CurveUnavailableError,
    build_curve,
    curve_date_for,
    forward_findings,
    years_between,
    zero_rate,
)
from actuarycanary.io.excel import SOURCE_ROW

DAY = date(2025, 12, 31)


def rows(
    points: list[tuple[int, float]],
    rate_type: str = "SPOT",
    compounding: str = "ANNUAL",
    curve: str = "C",
    day: date = DAY,
    currency: str = "TRY",
) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "curve_id": curve,
                "date": day,
                "tenor_months": months,
                "rate": rate,
                "rate_type": rate_type,
                "compounding": compounding,
                "currency": currency,
                "source": "TEST",
                SOURCE_ROW: index + 2,
            }
            for index, (months, rate) in enumerate(points)
        ]
    )


def curve_of(points: list[tuple[int, float]], **kwargs: Any):  # noqa: ANN201
    return build_curve(rows(points, **kwargs), "C", DAY)[0]


def test_a_flat_annual_curve_discounts_as_one_over_one_plus_r_to_the_t() -> None:
    curve = curve_of([(12, 0.10), (36, 0.10), (120, 0.10)])
    t = np.array([0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 7.3, 10.0])
    assert curve.discount_factors(t) == pytest.approx(1.1 ** (-t), rel=1e-14)


def test_the_spec_example_two_cash_flows_at_a_flat_ten_per_cent() -> None:
    # RS04: 100 at 0.5 and 1.5 years on a flat 10 per cent annual curve
    curve = curve_of([(12, 0.10), (24, 0.10)])
    present = 100 * curve.discount_factors(np.array([0.5, 1.5])).sum()
    assert present == pytest.approx(100 / 1.1**0.5 + 100 / 1.1**1.5, rel=1e-14)


def test_zero_rates_of_the_three_compoundings() -> None:
    assert zero_rate(0.10, 2.0, "ANNUAL") == pytest.approx(np.log(1.1))
    assert zero_rate(0.10, 2.0, "CONTINUOUS") == 0.10
    assert zero_rate(0.10, 0.5, "SIMPLE") == pytest.approx(np.log(1.05) / 0.5)
    assert zero_rate(-3.0, 1.0, "SIMPLE") is None  # 1 + r t = -2


def test_interpolation_is_linear_in_the_negative_log_discount_factor() -> None:
    curve = curve_of([(12, 0.05), (36, 0.07)])
    low, high = np.log(1.05), 3 * np.log(1.07)
    # between the tenors: halfway in L at t = 2
    assert curve.minus_log_discount(np.array([2.0]))[0] == pytest.approx((low + high) / 2)
    # before the first tenor z is flat at the first point
    assert curve.minus_log_discount(np.array([0.5]))[0] == pytest.approx(0.5 * np.log(1.05))
    # beyond the last tenor the last forward rate (the slope of L on 1 to 3 years) is held flat
    forward = (high - low) / 2
    assert curve.last_forward == pytest.approx(forward)
    assert curve.minus_log_discount(np.array([5.0]))[0] == pytest.approx(high + 2 * forward)


def test_a_discount_factor_at_or_before_today_is_one() -> None:
    curve = curve_of([(12, 0.3)])
    assert curve.discount_factors(np.array([-1.0, 0.0])).tolist() == [1.0, 1.0]


def test_a_flat_par_curve_gives_a_flat_spot_curve() -> None:
    # a bond paying the par rate c at par is worth 1 on a flat curve with D(n) = (1 + c)^-n
    curve = curve_of([(12, 0.06), (24, 0.06), (36, 0.06), (48, 0.06), (60, 0.06)], rate_type="PAR")
    assert curve.tenors.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert np.exp(-curve.log_discount) == pytest.approx(1.06 ** (-curve.tenors), rel=1e-13)


def test_the_par_bootstrap_by_hand() -> None:
    curve = curve_of([(12, 0.05), (24, 0.06)], rate_type="PAR")
    d1 = 1 / 1.05
    d2 = (1 - 0.06 * d1) / 1.06
    assert np.exp(-curve.log_discount) == pytest.approx([d1, d2], rel=1e-14)


def test_missing_whole_years_of_a_par_curve_are_interpolated_in_the_rate_first() -> None:
    sparse = curve_of([(12, 0.05), (36, 0.07)], rate_type="PAR")
    filled = curve_of([(12, 0.05), (24, 0.06), (36, 0.07)], rate_type="PAR")
    assert sparse.tenors.tolist() == [1.0, 2.0, 3.0]
    assert sparse.log_discount == pytest.approx(filled.log_discount, rel=1e-14)


def test_a_par_bootstrap_with_a_discount_factor_at_or_below_zero_makes_the_curve_unavailable() -> (
    None
):
    with pytest.raises(CurveUnavailableError, match="2-year"):
        curve_of([(12, 0.5), (24, 5.0)], rate_type="PAR")


def test_one_year_forwards_accumulate_from_the_first_year() -> None:
    curve = curve_of([(12, 0.05), (24, 0.06), (36, 0.08)], rate_type="FORWARD")
    expected = np.cumsum(np.log1p([0.05, 0.06, 0.08]))
    assert curve.log_discount == pytest.approx(expected, rel=1e-14)
    table = curve.table()
    assert table["forward_rate"].to_list() == pytest.approx([0.05, 0.06, 0.08], rel=1e-12)


def test_simple_points_with_a_non_positive_growth_are_excluded_and_listed() -> None:
    curve, findings = build_curve(
        rows([(6, 0.04), (12, -2.0), (24, 0.05)], compounding="SIMPLE"), "C", DAY
    )
    assert curve.tenors.tolist() == [0.5, 2.0]
    assert [(f.rule, f.count, f.rows) for f in findings] == [("CV10", 1, (3,))]


def test_a_curve_with_no_usable_point_is_unavailable() -> None:
    with pytest.raises(CurveUnavailableError, match="no usable point"):
        build_curve(rows([(12, -2.0)], compounding="SIMPLE"), "C", DAY)
    with pytest.raises(CurveUnavailableError, match="no points"):
        build_curve(rows([(12, 0.1)]), "OTHER", DAY)


def test_the_curve_table_gives_zero_rate_discount_factor_and_forward() -> None:
    table = curve_of([(12, 0.10), (24, 0.10)]).table()
    assert table["tenor_years"].to_list() == [1.0, 2.0]
    assert table["zero_rate"].to_list() == pytest.approx([np.log(1.1)] * 2)
    assert table["discount_factor"].to_list() == pytest.approx([1 / 1.1, 1 / 1.21])
    assert table["forward_rate"].to_list() == pytest.approx([0.1, 0.1])


def test_years_are_days_over_365_25() -> None:
    assert years_between(date(2024, 1, 1), date(2025, 1, 1)) == 366 / 365.25
    assert years_between(DAY, DAY) == 0.0


def test_the_curve_date_is_the_latest_one_on_or_before_the_discount_date() -> None:
    frame = pl.concat(
        [
            rows([(12, 0.1)], day=date(2025, 10, 31)),
            rows([(12, 0.1)], day=date(2025, 12, 31)),
            rows([(12, 0.1)], day=date(2026, 1, 31)),
        ]
    )
    assert curve_date_for(frame, "C", date(2025, 12, 31)) == (date(2025, 12, 31), "")
    assert curve_date_for(frame, "C", date(2025, 12, 15)) == (date(2025, 10, 31), "")
    found, reason = curve_date_for(frame, "C", date(2025, 9, 1))
    assert found is None and "DV-IRT-08" in reason
    found, reason = curve_date_for(frame, "NONE", DAY)
    assert found is None and "NONE" in reason


def test_dv_irt_09_lists_a_forward_below_the_floor_or_a_jump_between_tenors() -> None:
    assert forward_findings(curve_of([(12, 0.1), (24, 0.1), (36, 0.1)])) is None
    steep = forward_findings(curve_of([(12, 0.05), (24, 0.05), (36, 0.60)]))
    assert steep is not None and steep.rule == "DV-IRT-09" and steep.severity == "INFO"
    negative = forward_findings(curve_of([(12, 0.0), (24, -0.04)]))
    assert negative is not None and negative.count >= 1
