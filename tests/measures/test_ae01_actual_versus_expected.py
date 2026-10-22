"""AE01 Actual versus expected development: hand-computed fixtures of the specification."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.measures.port import Selection
from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.measures.helpers import make_inputs, measure, one
from tests.measures.shared import Selected
from tests.quality.builders import cv

V0, V1 = date(2023, 12, 31), date(2024, 12, 31)


def _ae_triangles(incurred: list[list[float]]) -> TriangleSet:
    cells = np.array(incurred)
    points = (V0, V1)

    def build(name: str) -> Triangle:
        return Triangle(
            name,
            ("S", "L"),
            ("2022",),
            (12, 24),
            cells,
            np.full(cells.shape, 5),
            np.zeros(cells.shape, int),
            points,
        )

    return TriangleSet(
        TriangleSettings(),
        "TRY",
        V1,
        "accident",
        0,
        5,
        (build("paid"), build("incurred")),
        pl.DataFrame(),
        (),
    )


def test_ae01_actual_over_expected_development() -> None:
    """Incurred 600 at age 12, CDF 1.5 at 12 and 1.2 at 24, incurred 780 at the later valuation:
    E = 900 (1/1.2 - 1/1.5) = 150, A = 180, AE = 1.2."""
    selection = Selection(
        V0, {("S", "L", "2022"): 900.0}, {("incurred", "S", "L"): {12: 1.5, 24: 1.2}}
    )
    inputs = make_inputs(
        {"claim_valuations": [cv(12)]},
        cut_off=V1,
        triangles=_ae_triangles([[600.0, 780.0]]),
        methods=Selected(selection),
    )
    result = measure(inputs, "AE01", "origin_period")
    assert one(result, "numerator") == pytest.approx(180.0)
    assert one(result, "denominator") == pytest.approx(150.0)
    assert one(result) == pytest.approx(1.2)


def test_ae01_expected_zero_shows_the_difference_only() -> None:
    selection = Selection(
        V0, {("S", "L", "2022"): 900.0}, {("incurred", "S", "L"): {12: 1.5, 24: 1.5}}
    )
    inputs = make_inputs(
        {"claim_valuations": [cv(12)]},
        cut_off=V1,
        triangles=_ae_triangles([[600.0, 780.0]]),
        methods=Selected(selection),
    )
    result = measure(inputs, "AE01", "origin_period")
    assert one(result) is None and one(result, "difference") == pytest.approx(-180.0 + 360.0)
    assert "expected movement is zero" in one(result, "note")


def test_ae01_without_the_selection_says_so() -> None:
    inputs = make_inputs(
        {"claim_valuations": [cv(12)]}, cut_off=V1, triangles=_ae_triangles([[600.0, 780.0]])
    )
    assert "not built yet" in measure(inputs, "AE01").reason
