"""A hand-worked book of three claims, one per accident year, for RC03 and RC04."""

from datetime import date
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.measures.model import MeasureInputs
from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.measures.helpers import make_inputs

NAN = np.nan
GROUP = ("NON_LIFE", "L")
CUT_OFF = date(2024, 12, 31)
SUB, SAL, OTHER = "RECOVERY_SUBROGATION", "RECOVERY_SALVAGE", "RECOVERY_OTHER"


def valuation(claim: str, day: date, paid: float, sub: float = 0.0, sal: float = 0.0) -> dict:
    return {
        "claim_id": claim,
        "valuation_date": day,
        "paid_to_date": paid,
        "case_reserve": 0.0,
        "status": "OPEN",
        "currency": "TRY",
        "subrogation_to_date": sub,
        "salvage_to_date": sal,
    }


# claim A (2022): first paid in January 2022; subrogation 10 in June 2022 and 30 more in
# February 2024, salvage 20 in March 2023. Claim B (2023): subrogation 15 in May 2024.
# Claim C (2024): paid, nothing recovered.
VALUATIONS = [
    valuation("A", date(2022, 1, 31), 60.0),
    valuation("A", date(2022, 6, 30), 100.0, sub=10.0),
    valuation("A", date(2023, 3, 31), 200.0, sub=10.0, sal=20.0),
    valuation("A", date(2024, 2, 29), 300.0, sub=40.0, sal=20.0),
    valuation("B", date(2023, 11, 30), 50.0),
    valuation("B", date(2024, 5, 31), 150.0, sub=15.0),
    valuation("C", date(2024, 10, 31), 80.0),
]
CLAIMS = [
    {"claim_id": c, "occurrence_date": d, "report_date": d, "segment": GROUP[0], "line": GROUP[1]}
    for c, d in (("A", date(2022, 1, 10)), ("B", date(2023, 9, 1)), ("C", date(2024, 8, 1)))
]


def booking(number: int, claim: str, day: date, amount: float, kind: str, **more: Any) -> dict:
    return {
        "transaction_id": f"R{number}",
        "claim_id": claim,
        "booking_date": day,
        "amount": amount,
        "currency": "TRY",
        "type": kind,
        **more,
    }


BOOKINGS = [
    booking(1, "A", date(2022, 6, 15), 10.0, SUB),
    booking(2, "A", date(2023, 3, 1), 20.0, SAL),
    booking(3, "A", date(2024, 2, 1), 30.0, SUB),
    booking(4, "B", date(2024, 5, 5), 15.0, SUB),
]
PAID = [[100.0, 200.0, 300.0], [50.0, 150.0, NAN], [80.0, NAN, NAN]]


def triangle_set(paid: list[list[float]] = PAID) -> TriangleSet:
    points = (date(2022, 12, 31), date(2023, 12, 31), CUT_OFF)
    cumulative = np.array(paid, dtype=float)
    counts = np.where(np.isnan(cumulative), -1, 1)
    calendar = np.where(np.isnan(cumulative), -1, 0)
    triangles = tuple(
        Triangle(
            name,
            GROUP,
            ("2022", "2023", "2024"),
            (12, 24, 36),
            cumulative,
            counts,
            calendar,
            points,
        )
        for name in ("paid", "incurred")  # no case reserves in this book
    )
    return TriangleSet(
        TriangleSettings(), "TRY", CUT_OFF, "accident", 0, 3, triangles, pl.DataFrame(), ()
    )


def book(
    bookings: list[dict] | None = None,
    valuations: list[dict] | None = None,
    triangles: bool = True,
) -> MeasureInputs:
    """Inputs with the recoveries feed (`bookings`) or without it (None: derived flows)."""
    rows: dict[str, list[dict]] = {
        "claim_valuations": VALUATIONS if valuations is None else valuations,
        "claims": CLAIMS,
    }
    if bookings is not None:
        rows["recoveries"] = bookings
    inputs = make_inputs(rows, cut_off=CUT_OFF)
    if triangles:
        inputs.triangles = triangle_set()
    return inputs
