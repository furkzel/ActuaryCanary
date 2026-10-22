"""CL10 Paid-to-incurred ratio: hand-computed fixtures of the specification."""

from datetime import date

import numpy as np
import polars as pl

from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.measures.helpers import make_inputs, measure, table, values
from tests.quality.builders import cv

NAN = np.nan


def _triangle_set(paid: list[list[float]], incurred: list[list[float]]) -> TriangleSet:
    ages = (12, 24, 36)
    origins = ("2022", "2023", "2024")
    points = (date(2022, 12, 31), date(2023, 12, 31), date(2024, 12, 31))

    def build(measure_name: str, cells: list[list[float]]) -> Triangle:
        cumulative = np.array(cells, dtype=float)
        counts = np.where(np.isnan(cumulative), -1, 3)
        calendar = np.where(np.isnan(cumulative), -1, 0)
        return Triangle(
            measure_name, ("S", "L"), origins, ages, cumulative, counts, calendar, points
        )

    return TriangleSet(
        TriangleSettings(),
        "TRY",
        points[-1],
        "accident",
        0,
        9,
        (build("paid", paid), build("incurred", incurred)),
        pl.DataFrame(),
        (),
    )


def test_cl10_paid_to_incurred_cell_by_cell() -> None:
    paid = [[10.0, 20.0, 25.0], [12.0, 24.0, NAN], [15.0, NAN, NAN]]
    incurred = [[20.0, 25.0, 26.0], [24.0, 30.0, NAN], [30.0, NAN, NAN]]
    inputs = make_inputs({"claim_valuations": [cv(1)]}, triangles=_triangle_set(paid, incurred))
    result = measure(inputs, "CL10", "origin_period", "development_period")
    assert table(result) == {
        ("2022", "12"): 0.5,
        ("2022", "24"): 0.8,
        ("2022", "36"): 25 / 26,
        ("2023", "12"): 0.5,
        ("2023", "24"): 0.8,
        ("2024", "12"): 0.5,
    }


def test_cl10_zero_incurred_is_not_computed_and_above_one_is_flagged() -> None:
    paid = [[0.0, 30.0, NAN], [NAN, NAN, NAN], [NAN, NAN, NAN]]
    incurred = [[0.0, 25.0, NAN], [NAN, NAN, NAN], [NAN, NAN, NAN]]
    inputs = make_inputs({"claim_valuations": [cv(1)]}, triangles=_triangle_set(paid, incurred))
    result = measure(inputs, "CL10", "origin_period", "development_period")
    assert table(result) == {("2022", "12"): None, ("2022", "24"): 1.2}
    assert "negative case reserves" in " ".join(values(result, "note"))


def test_cl10_without_triangles_says_so() -> None:
    result = measure(make_inputs({"claim_valuations": [cv(1)]}), "CL10")
    assert result.reason == "no triangles were built (MT01)"
