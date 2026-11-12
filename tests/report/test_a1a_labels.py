"""A1a: the curve table names what each column holds (R03, record 0751) and the reserve-range
rows say which quantity they hold (R19)."""

from datetime import date
from enum import Enum
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.yield_curve import build_curve
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.report import language
from actuarycanary.report.uncertainty_section import curve

DAY = date(2025, 12, 31)


def _rows(points: list[tuple[int, float]], rate_type: str, compounding: str) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "curve_id": "C",
                "date": DAY,
                "tenor_months": months,
                "rate": rate,
                "rate_type": rate_type,
                "compounding": compounding,
                "currency": "TRY",
                "source": "TEST",
                SOURCE_ROW: i + 2,
            }
            for i, (months, rate) in enumerate(points)
        ]
    )


class _Timing(Enum):
    MID_PERIOD = "mid_period"


def _shown(points: list[tuple[int, float]], rate_type: str, compounding: str) -> dict:
    built, _ = build_curve(_rows(points, rate_type, compounding), "C", DAY)
    result = SimpleNamespace(
        discount=SimpleNamespace(
            curve=built, discount_date=DAY, timing=_Timing.MID_PERIOD, tail_payment_years=3
        )
    )
    shown = curve(result, built.table())  # type: ignore[arg-type]
    assert shown is not None
    return {"built": built, "shown": shown}


def test_annual_points_show_input_and_zero_rates_and_d_is_one_plus_r_to_minus_t() -> None:
    out = _shown([(12, 0.10), (24, 0.12), (60, 0.15)], "SPOT", "ANNUAL")
    built = out["built"]
    t = built.tenors
    r = np.array([0.10, 0.12, 0.15])
    assert built.input_rates() == pytest.approx(r, rel=1e-13)
    table = built.table()
    assert table["discount_factor"].to_numpy() == pytest.approx((1 + r) ** (-t), rel=1e-13)
    assert table["zero_rate"].to_numpy() == pytest.approx(np.log1p(r), rel=1e-13)
    first = out["shown"]["points"][0]
    # CV06: ratios to one decimal as percent, factors to three decimals
    assert (first["input"], first["zero"], first["factor"]) == ("10.0%", "9.5%", "0.909")


def test_the_headings_name_what_the_columns_hold() -> None:
    shown = _shown([(12, 0.10), (24, 0.12)], "SPOT", "ANNUAL")["shown"]
    assert shown["input_heading"] == "Input rate (spot rate, ANNUAL)"
    with language.using("tr"):
        again = _shown([(12, 0.10), (24, 0.12)], "SPOT", "ANNUAL")["shown"]
        assert "ANNUAL" in again["input_heading"] and "Input" not in again["input_heading"]
    template = (
        __import__("pathlib").Path(__file__).parents[2]
        / "src/actuarycanary/report/templates/uncertainty.html.j2"
    ).read_text(encoding="utf-8")
    for heading in (
        "Zero rate, continuously compounded",
        "Forward rate, annually compounded, from the previous tenor",
        "Discount factor",
    ):
        assert f'tr("{heading}")' in template


@pytest.mark.parametrize(
    ("rate_type", "compounding", "rate"),
    [("SPOT", "CONTINUOUS", 0.08), ("SPOT", "SIMPLE", 0.08), ("PAR", "ANNUAL", 0.08)],
)
def test_the_input_rate_is_recovered_for_the_other_types(
    rate_type: str, compounding: str, rate: float
) -> None:
    points = [(12, rate), (24, rate), (36, rate)]
    built, _ = build_curve(_rows(points, rate_type, compounding), "C", DAY)
    assert built.input_rates() == pytest.approx([rate] * 3, rel=1e-12)


def test_the_forward_input_is_the_annual_forward_rate() -> None:
    built, _ = build_curve(_rows([(12, 0.05), (24, 0.07)], "FORWARD", "ANNUAL"), "C", DAY)
    assert built.input_rates() == pytest.approx([0.05, 0.07], rel=1e-13)


def test_the_range_rows_say_unpaid_and_ibnr_not_paid_and_incurred() -> None:
    from actuarycanary.report.charts import range_row_label

    assert range_row_label("paid") == "Unpaid (paid triangle)"
    assert range_row_label("incurred") == "IBNR (incurred triangle)"
    with language.using("tr"):
        assert range_row_label("paid") != "Unpaid (paid triangle)"


def test_the_appendix_gets_the_state_each_module_had_in_the_run() -> None:
    from actuarycanary.report.render import RUN_STATE_MARK, with_run_states

    html = (
        f"<td>{RUN_STATE_MARK.format(module='M04')}</td>"
        f"<td>{RUN_STATE_MARK.format(module='M05')}</td>"
    )
    runs = {
        "M04": {"state": "limited", "why": "MT14 did not run for 2 of 8 <triangles>"},
        "M05": {"state": "ran", "why": ""},
    }
    shown = with_run_states(html, runs)
    assert "<td>limited: MT14 did not run for 2 of 8 &lt;triangles&gt;</td>" in shown
    assert "<td>ran</td>" in shown
    assert "run-state" not in shown
