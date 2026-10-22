"""Properties of the bases over random books: CV03 net = gross - ceded, cumulative of the
incremental triangle is the cumulative triangle (MT01), row order does not matter.

Each example builds several triangle sets, so these run with the slow tests."""

import calendar
from datetime import date

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSet, TriangleSettings, build_triangles
from tests.convert.fixtures import market

pytestmark = pytest.mark.slow

MONTHS = range(1, 7)
BOOK_MARKET = market(
    [
        row
        for m in MONTHS
        for row in (
            ("CPI_TR", "PRICE_INDEX", date(2024, m, 28), 100.0 * 1.1**m),
            ("USD/TRY", "FX_PERIOD_AVERAGE", date(2024, m, 15), 30.0 + 2 * m),
            ("USD/TRY", "FX_PERIOD_END", date(2024, m, 28), 31.0 + 2 * m),
            ("TRY/EUR", "FX_PERIOD_AVERAGE", date(2024, m, 15), 1 / (40.0 + 3 * m)),
            ("TRY/EUR", "FX_PERIOD_END", date(2024, m, 28), 1 / (41.0 + 3 * m)),
        )
    ]
)
RATES = {"TRY": 1.0, "USD": 42.0, "EUR": 60.0}


@st.composite
def books(draw: st.DrawFn) -> pl.DataFrame:
    rows: list[tuple] = []
    for claim in range(draw(st.integers(1, 3))):
        currency = draw(st.sampled_from(["TRY", "USD", "EUR"]))
        paid = ceded_paid = 0
        for month in sorted(draw(st.sets(st.sampled_from(list(MONTHS)), min_size=1, max_size=4))):
            step = draw(st.integers(0, 500))
            paid += step
            ceded_paid += draw(st.integers(0, step))
            reserve = draw(st.integers(0, 300))
            ceded_reserve = draw(st.integers(0, reserve))
            day = date(2024, month, calendar.monthrange(2024, month)[1])
            rows.append((f"C{claim}", currency, day, paid, reserve, ceded_paid, ceded_reserve))
    return pl.DataFrame(
        {
            "claim_id": [r[0] for r in rows],
            "currency": [r[1] for r in rows],
            "valuation_date": [r[2] for r in rows],
            "paid_to_date": [float(r[3]) for r in rows],
            "case_reserve": [float(r[4]) for r in rows],
            "ceded_paid_to_date": [float(r[5]) for r in rows],
            "ceded_reserve": [float(r[6]) for r in rows],
            "status": ["OPEN"] * len(rows),
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        }
    )


def _build(frame: pl.DataFrame, reinsurance: str, value: str) -> TriangleSet:
    settings = TriangleSettings(
        reinsurance_basis=ReinsuranceBasis(reinsurance),
        value_basis=ValueBasis(value),
        origin_period=Period.MONTH,
        development_period=Period.MONTH,
    )
    return build_triangles(
        frame,
        None,
        settings,
        RATES,
        "TRY",
        market=BOOK_MARKET,
        price_index="CPI_TR",
        measures=("paid", "case_reserve", "incurred"),
    )


@pytest.mark.parametrize("value", ["NOMINAL", "INFLATION_ADJUSTED"])
@given(frame=books())
def test_cv03_net_equals_gross_minus_ceded(frame: pl.DataFrame, value: str) -> None:
    gross, ceded, net = (_build(frame, b, value) for b in ("GROSS", "CEDED", "NET"))
    for a, b, c in zip(gross.triangles, ceded.triangles, net.triangles, strict=True):
        np.testing.assert_allclose(
            c.cumulative, a.cumulative - b.cumulative, atol=1e-6, rtol=1e-9, equal_nan=True
        )


@given(frame=books())
def test_mt01_cumulative_of_the_incremental_triangle_is_the_cumulative_triangle(
    frame: pl.DataFrame,
) -> None:
    for triangle in _build(frame, "NET", "INFLATION_ADJUSTED").triangles:
        incremental = np.where(triangle.observed, triangle.incremental, 0.0)
        np.testing.assert_allclose(
            np.cumsum(incremental, axis=1)[triangle.observed],
            triangle.cumulative[triangle.observed],
            atol=1e-6,
            rtol=1e-9,
        )


@given(frame=books(), seed=st.integers(0, 1000))
def test_results_do_not_depend_on_row_order(frame: pl.DataFrame, seed: int) -> None:
    shuffled = frame.sample(fraction=1.0, shuffle=True, seed=seed)
    one = _build(frame, "NET", "INFLATION_ADJUSTED")
    two = _build(shuffled, "NET", "INFLATION_ADJUSTED")
    for a, b in zip(one.triangles, two.triangles, strict=True):
        np.testing.assert_allclose(a.cumulative, b.cumulative, atol=1e-6, rtol=1e-9, equal_nan=True)
