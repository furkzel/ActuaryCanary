"""A1a: one reconciled total (R07), the bridge from the selected unpaid to the simulated mean
(R05) and the present-value tables that hold one definition each (R06), record 0752."""

from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from actuarycanary.modules.uncertainty import ALL_LINES, DISCOUNTED, NOMINAL
from actuarycanary.report.uncertainty_section import (
    bridge_of,
    bridge_table,
    headline,
    present_values,
    selected_totals,
)

ORIGINS = ("2020", "2021", "2022")


def test_the_bridge_of_a_scaled_line_adds_up_to_the_cent() -> None:
    # origin 2022 is fully developed in the simulated triangle: selected 20.50, simulated 0
    selected = np.array([100.0, 50.0, 20.5])
    sims = np.array([[90.0, 40.0, 0.0], [110.0, 60.0, 0.0], [95.0, 45.0, 0.0], [105.0, 55.0, 0.0]])
    found = bridge_of(ORIGINS, selected, sims)
    assert found.selected == 170.5
    assert found.left_out == 20.5 and found.left_out_origins == (("2022", 20.5),)
    assert found.other == pytest.approx(0.0, abs=1e-12)
    assert found.mean == 150.0
    assert round(found.balance, 2) == round(found.mean, 2) == 150.0


def test_the_bridge_of_an_unscaled_line_keeps_the_sampling_difference_in_its_own_step() -> None:
    selected = np.array([100.0, 50.0])
    sims = np.array([[101.0, 49.0], [103.0, 51.0]])  # means 102 and 50
    found = bridge_of(ORIGINS[:2], selected, sims)
    assert found.left_out == 0.0 and found.left_out_origins == ()
    assert found.other == pytest.approx(2.0)
    assert found.selected - found.left_out + found.other == pytest.approx(152.0)


def test_an_origin_with_nothing_selected_is_not_left_out() -> None:
    found = bridge_of(ORIGINS[:2], np.array([0.0, 10.0]), np.array([[0.0, 9.0], [0.0, 11.0]]))
    assert found.left_out == 0.0 and found.left_out_origins == ()
    assert found.other == 0.0 and found.mean == 10.0
    noise = bridge_of(ORIGINS[:2], np.array([-1.86e-9, 10.0]), np.array([[0.0, 9.0], [0.0, 11.0]]))
    assert noise.left_out == 0.0 and noise.left_out_origins == ()


def _risk(rows: list[tuple[str, str, str, str, float, float | None, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "segment": a,
                "line": b,
                "origin_period": "Total",
                "source": src,
                "value_basis": basis,
                "mean": mean,
                "nominal_mean": before,
                "discount_effect": effect,
                "p95": mean * 1.2,
                "standard_deviation": mean * 0.1,
                "coefficient_of_variation": 0.1,
            }
            for a, b, src, basis, mean, before, effect in rows
        ]
    )


def test_the_discounted_headline_row_adds_up_and_the_expected_cash_flows_have_their_own_table() -> (
    None
):
    risk = _risk(
        [
            ("S", "L", "bootstrap", DISCOUNTED, 60.0, 100.0, 40.0),
            ("S", "L", "expected_cash_flows", DISCOUNTED, 62.0, 101.0, 39.0),
        ]
    )
    [row] = headline(risk, pl.DataFrame(), DISCOUNTED, {("S", "L"): 101.0})
    assert (row["nominal"], row["effect"], row["reserve"]) == ("100", "40", "60")
    assert float(row["nominal"]) - float(row["effect"]) == float(row["reserve"])
    [pv] = present_values(risk)
    assert (pv["selected"], pv["effect"], pv["present"]) == ("101", "39", "62")
    assert float(pv["selected"]) - float(pv["effect"]) == float(pv["present"])


def test_the_total_of_all_lines_is_the_sum_of_the_selected_unpaid_of_the_lines() -> None:
    class _Line:
        def __init__(self, key: tuple[str, str], total: float) -> None:
            self.key, self.selected_total = key, total

    totals = selected_totals((_Line(("A", "x"), 10.5), _Line(("A", "y"), 4.25)))  # type: ignore[arg-type]
    assert totals[(ALL_LINES, ALL_LINES)] == 14.75
    assert selected_totals(()) == {}


class _Line:
    def __init__(
        self, key: tuple[str, str], selected: list[float], sims: list[list[float]]
    ) -> None:
        self.key = key
        self.origins = ORIGINS[: len(selected)]
        self.selected_unpaid = np.array(selected)
        self.origin_sims = np.array(sims) if sims else None
        self.selected_total = float(np.sum(selected))


def test_the_bridge_table_has_the_steps_as_rows_and_the_lines_and_all_lines_as_columns() -> None:
    a = _Line(("S", "A"), [100.0, 50.0, 20.5], [[90.0, 40.0, 0.0], [110.0, 60.0, 0.0]])
    b = _Line(("S", "B"), [10.0, 0.0], [[9.0, 0.0], [11.0, 0.0]])
    risk = _risk(
        [
            ("S", "A", "bootstrap", DISCOUNTED, 100.0, 150.0, 50.0),
            ("S", "B", "bootstrap", DISCOUNTED, 8.0, 10.0, 2.0),
        ]
    )
    result = SimpleNamespace(lines=(a, b), risk=risk)
    nominal = bridge_table(result, NOMINAL)  # type: ignore[arg-type]
    assert nominal is not None
    assert nominal["heads"] == ["S · A", "S · B", "All lines"]
    steps = dict(nominal["steps"])
    assert steps["Selected unpaid"] == ["171", "10", "181"]
    assert steps["less the origins without simulated development"] == ["-21", "0", "-21"]
    assert steps["plus the difference of the simulation for the other origins"] == ["0", "0", "0"]
    assert steps["Mean of the simulation, nominal"] == ["150", "10", "160"]
    assert nominal["left_out"] == [{"line": "S · A", "origin": "2022", "amount": "21"}]
    discounted = bridge_table(result, DISCOUNTED)  # type: ignore[arg-type]
    assert discounted is not None
    steps = dict(discounted["steps"])
    assert steps["less the discount effect on the simulated mean (RS05)"] == ["-50", "-2", "-52"]
    assert steps["Mean of the simulation, present value"] == ["100", "8", "108"]


def test_a_line_without_a_simulation_shows_dashes_and_no_total() -> None:
    a = _Line(("S", "A"), [100.0], [[100.0]])
    c = _Line(("S", "C"), [5.0], [])
    table = bridge_table(SimpleNamespace(lines=(a, c), risk=_risk([])), NOMINAL)  # type: ignore[arg-type]
    assert table is not None and table["heads"] == ["S · A", "S · C"]
    assert dict(table["steps"])["Mean of the simulation, nominal"] == ["100", "–"]
    only = bridge_table(SimpleNamespace(lines=(c,), risk=_risk([])), NOMINAL)  # type: ignore[arg-type]
    assert only is None
