"""MT01 triangle construction on a hand-computed fixture, plus properties and edge cases.

Fixture: three claims over the 30 month ends 2023-01 to 2025-06 (cut-off 2025-06-30).
A (accident 2023): rows 2023-02 to 2023-06 with April missing, closed 2023-12, reopened
2024-08, closed again 2025-01. B (accident 2023, reported 2024-01). C (accident 2024).
"""

from datetime import date
from typing import Any

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import Period, month_end
from actuarycanary.structures.triangles import (
    UNKNOWN,
    TriangleError,
    TriangleSet,
    TriangleSettings,
    build_triangles,
)

TRY = {"TRY": 1.0}
TOLERANCE = 1e-9  # MT01 fixture: exact (1e-9 absolute)

# claim, valuation date, paid_to_date, case_reserve, status
ROWS = [
    ("A", date(2023, 2, 28), 0.0, 100.0, "OPEN"),
    ("A", date(2023, 3, 31), 20.0, 80.0, "OPEN"),
    ("A", date(2023, 5, 31), 50.0, 60.0, "OPEN"),
    ("A", date(2023, 6, 30), 50.0, 60.0, "OPEN"),
    ("A", date(2023, 12, 31), 120.0, 0.0, "CLOSED"),
    ("A", date(2024, 8, 31), 120.0, 30.0, "REOPENED"),
    ("A", date(2025, 1, 31), 160.0, 0.0, "CLOSED"),
    ("B", date(2024, 1, 31), 0.0, 200.0, "OPEN"),
    ("B", date(2024, 6, 30), 70.0, 150.0, "OPEN"),
    ("B", date(2025, 3, 31), 210.0, 40.0, "OPEN"),
    ("C", date(2024, 7, 31), 10.0, 40.0, "OPEN"),
    ("C", date(2025, 6, 30), 30.0, 20.0, "OPEN"),
]
OCCURRENCE = {"A": date(2023, 2, 10), "B": date(2023, 11, 20), "C": date(2024, 7, 15)}
GROUP = ("NON_LIFE", "MOTOR_OD")


def _valuations(rows: list[tuple[Any, ...]] = ROWS, currency: dict[str, str] | None = None):
    currency = currency or {}
    return pl.DataFrame(
        {
            "claim_id": [r[0] for r in rows],
            "valuation_date": [r[1] for r in rows],
            "paid_to_date": [r[2] for r in rows],
            "case_reserve": [r[3] for r in rows],
            "status": [r[4] for r in rows],
            "currency": [currency.get(r[0], "TRY") for r in rows],
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        },
        schema_overrides={"paid_to_date": pl.Float64, "case_reserve": pl.Float64},
    )


def _claims(ids: tuple[str, ...] = ("A", "B", "C"), **dates: date | None) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "claim_id": list(ids),
            "occurrence_date": [dates.get(c, OCCURRENCE[c]) for c in ids],
            "report_date": [OCCURRENCE[c] for c in ids],
            "segment": [GROUP[0]] * len(ids),
            "line": [GROUP[1]] * len(ids),
            SOURCE_ROW: list(range(2, len(ids) + 2)),
        },
        schema_overrides={"occurrence_date": pl.Date},
    )


def _build(
    valuations: pl.DataFrame | None = None,
    claims: pl.DataFrame | None = None,
    development: Period = Period.YEAR,
    rates: dict[str, float] = TRY,
    with_claims: bool = True,
) -> TriangleSet:
    return build_triangles(
        _valuations() if valuations is None else valuations,
        (_claims() if claims is None else claims) if with_claims else None,
        TriangleSettings(development_period=development),
        rates,
        "TRY",
    )


def _assert_cells(actual: np.ndarray, expected: list[list[float | None]]) -> None:
    wanted = np.array([[np.nan if v is None else v for v in row] for row in expected])
    np.testing.assert_allclose(actual, wanted, rtol=0, atol=TOLERANCE, equal_nan=True)


def test_annual_triangles_by_hand() -> None:
    result = _build()
    assert result.cut_off == date(2025, 6, 30)
    assert result.origin_basis == "accident"
    paid = result.get("paid", GROUP)
    assert paid.origins == ("2023", "2024", "2025")
    assert paid.ages == (6, 18, 30)  # mid-year cut-off (decision 0008)
    _assert_cells(paid.cumulative, [[50, 190, 370], [0, 30, None], [0, None, None]])
    _assert_cells(
        result.get("incurred", GROUP).cumulative,
        [[110, 340, 410], [0, 50, None], [0, None, None]],
    )
    assert paid.claim_counts.tolist() == [[1, 2, 2], [0, 1, -1], [0, -1, -1]]
    _assert_cells(paid.incremental, [[50, 140, 180], [0, 30, None], [0, None, None]])
    assert paid.latest.tolist() == [370, 30, 0]


def test_quarterly_development_of_annual_origins_by_hand() -> None:
    result = _build(development=Period.QUARTER)
    paid = result.get("paid", GROUP)
    incurred = result.get("incurred", GROUP)
    assert paid.ages == (3, 6, 9, 12, 15, 18, 21, 24, 27, 30)
    future = [None] * 4
    _assert_cells(
        paid.cumulative,
        [
            [20, 50, 50, 120, 120, 190, 190, 190, 370, 370],
            [0, 0, 10, 10, 10, 30, *future],
            [0, 0, *future, None, None, None, None],
        ],
    )
    _assert_cells(
        incurred.cumulative,
        [
            [100, 110, 110, 120, 320, 340, 370, 370, 410, 410],
            [0, 0, 50, 50, 50, 50, *future],
            [0, 0, *future, None, None, None, None],
        ],
    )
    assert paid.valuation_points[paid.calendar[1, 0]] == date(2024, 3, 31)
    assert paid.latest_index.tolist() == [9, 5, 1]


def test_empty_amount_row_is_left_out_and_the_previous_row_carries_forward() -> None:
    rows = [*ROWS, ("A", date(2023, 9, 30), None, 999.0, "OPEN")]  # DV-CLV-02
    result = _build(valuations=_valuations(rows), development=Period.QUARTER)
    assert result.get("paid", GROUP).cumulative[0, 2] == 50
    assert result.get("incurred", GROUP).cumulative[0, 2] == 110


def test_without_claims_origins_are_first_valuation_proxies() -> None:
    result = _build(with_claims=False)
    assert result.origin_basis == "first_valuation (proxy)"
    assert result.proxy_claims == 3
    paid = result.get("paid", (UNKNOWN, UNKNOWN))
    # A first valued 2023-02 -> 2023; B 2024-01 and C 2024-07 -> 2024
    _assert_cells(paid.cumulative, [[50, 120, 160], [70, 240, None], [0, None, None]])


def test_claim_without_header_uses_a_proxy_origin_and_the_set_is_mixed() -> None:
    result = _build(claims=_claims(("A", "B")))
    assert result.origin_basis.startswith("mixed")
    assert result.proxy_claims == 1
    assert result.get("paid", (UNKNOWN, UNKNOWN)).latest.tolist() == [0, 30, 0]


def test_claims_without_usable_origin_are_left_out_and_listed() -> None:
    result = _build(claims=_claims(B=None, C=date(2025, 9, 1)))
    assert result.claims_used == 1
    assert {f.rule for f in result.findings} == {"MT01", "DV-CLM-07"}
    assert result.get("paid", GROUP).latest.tolist() == [160, 0, 0]


def test_amounts_without_rate_are_not_converted_and_reported() -> None:
    result = _build(valuations=_valuations(currency={"B": "USD"}))
    assert result.get("paid", GROUP).latest.tolist() == [160, 30, 0]
    assert result.not_converted.to_dicts() == [
        {"currency": "USD", "claims": 1, "paid": 210.0, "incurred": 250.0}
    ]


def test_origin_length_must_be_a_whole_multiple_of_development_length() -> None:
    with pytest.raises(ValidationError, match="allowed development periods: MONTH, QUARTER"):
        TriangleSettings(origin_period=Period.QUARTER, development_period=Period.YEAR)


# --- properties ------------------------------------------------------------------------


@st.composite
def _histories(draw: st.DrawFn) -> pl.DataFrame:
    rows: list[tuple[Any, ...]] = []
    for claim in range(draw(st.integers(1, 6))):
        start = draw(st.integers(0, 30))
        months = draw(st.lists(st.integers(start, 35), min_size=1, max_size=8, unique=True))
        paid = 0.0
        for month in sorted(months):
            paid += draw(st.integers(0, 50))
            reserve = float(draw(st.integers(0, 80)))
            rows.append((f"{claim}", month_end(12 * 2022 + month), paid, reserve, "OPEN"))
    return _valuations(rows)


def _as_of_total(valuations: pl.DataFrame, column: str) -> float:
    last = valuations.sort("valuation_date").group_by("claim_id").agg(pl.all().last())
    return float(last[column].sum())


_DEVELOPMENT = st.sampled_from([Period.MONTH, Period.QUARTER, Period.YEAR])


@given(_histories(), _DEVELOPMENT)
def test_property_latest_diagonal_and_counts(valuations: pl.DataFrame, development: Period) -> None:
    result = _build(valuations=valuations, development=development, with_claims=False)
    paid = [t for t in result.triangles if t.measure == "paid"]
    latest_total = sum(float(t.latest.sum()) for t in paid)
    assert latest_total == pytest.approx(_as_of_total(valuations, "paid_to_date"), rel=1e-9)
    for triangle in result.triangles:
        counts = np.where(triangle.claim_counts < 0, np.iinfo(np.int64).max, triangle.claim_counts)
        assert (np.diff(counts, axis=1) >= 0).all()  # reported counts never decrease


@given(_histories(), _DEVELOPMENT, st.randoms())
def test_property_row_order_does_not_matter(
    valuations: pl.DataFrame, development: Period, random: Any
) -> None:
    result = _build(valuations=valuations, development=development, with_claims=False)
    order = list(range(valuations.height))
    random.shuffle(order)
    shuffled = _build(valuations=valuations[order], development=development, with_claims=False)
    for a, b in zip(result.triangles, shuffled.triangles, strict=True):
        np.testing.assert_array_equal(a.cumulative, b.cumulative)


def test_no_usable_origin_builds_no_triangle() -> None:
    with pytest.raises(TriangleError, match="no claim has a usable origin"):
        _build(claims=_claims(A=None, B=None, C=None))
