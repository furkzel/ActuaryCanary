# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false
"""The methods wired into the reserving module (M04) and behind the port of the measures.

Hand fixture of tests/fixtures/hand: annual origins 2021 to 2024, ages 12 to 48, premium 400,
440, 480, 520. Every expected number below is either worked by hand in the comment or
produced by calling the method itself on the same arrays, so these tests prove the wiring
(right triangle, right premium, right scope), not the methods again (tests/methods).
"""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.measures.port import NotAvailable, Selection
from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.bornhuetter_ferguson import bornhuetter_ferguson
from actuarycanary.methods.cape_cod import CapeCod, cape_cod
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.selection import Choice, select_ultimates
from actuarycanary.modules.methods_port import ReservingPort
from actuarycanary.modules.reserving import (
    UNDERWRITING_PREMIUM,
    ChainLadderSettings,
    MethodInputs,
    methods_run,
    not_run_notes,
    run_reserving,
    truncate_triangle,
)
from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.benchmarks.load import load_hand
from tests.measures.helpers import make_inputs, measure
from tests.quality.builders import cv

HAND = load_hand()
YEARS = [str(o) for o in HAND["incurred"]["origins"]]
AGES = tuple(HAND["incurred"]["ages"])
POINTS = tuple(date(int(y), 12, 31) for y in YEARS)
CUT_OFF, V0 = POINTS[-1], POINTS[-2]
GROUP = ("S", "L")
BASIS = "GROSS, REPORTING, NOMINAL"


def _array(name: str) -> np.ndarray:
    return np.array(
        [[np.nan if v is None else v for v in row] for row in HAND[name]["values"]], dtype=float
    )


def _triangle(measure_name: str) -> Triangle:
    cumulative = _array(measure_name)
    observed = ~np.isnan(cumulative)
    calendar = np.where(observed, np.add.outer(np.arange(4), np.arange(4)), -1)
    return Triangle(
        measure_name,
        GROUP,
        tuple(YEARS),
        AGES,
        cumulative,
        np.where(observed, 5, -1),
        calendar,
        POINTS,
    )


def _set(**changes: object) -> TriangleSet:
    return TriangleSet(
        TriangleSettings(),
        "TRY",
        CUT_OFF,
        "accident",
        0,
        20,
        (_triangle("paid"), _triangle("incurred")),
        pl.DataFrame(),
        (),
        **changes,  # type: ignore[arg-type]
    )


PREMIUM = pl.DataFrame(
    {
        "segment": ["S"] * 4,
        "line": ["L"] * 4,
        "origin_period": YEARS,
        "earned_premium": [float(HAND["premium"][o]) for o in HAND["incurred"]["origins"]],
    }
)
PREMIUM_ARRAY = np.array(PREMIUM["earned_premium"], dtype=float)


@pytest.fixture(scope="module")
def result():
    return run_reserving(_set(), ChainLadderSettings(), MethodInputs(premium=PREMIUM))


@pytest.fixture(scope="module")
def group(result):
    return result.groups[0]


def test_every_premium_based_method_runs_on_the_triangle_with_the_premium_of_its_origin(
    group,
) -> None:
    incurred = _array("incurred")
    chain = chain_ladder(incurred)
    assert isinstance(chain, ChainLadder)
    cape = cape_cod(chain, PREMIUM_ARRAY)
    assert isinstance(cape, CapeCod)
    direct = bornhuetter_ferguson(chain, PREMIUM_ARRAY, cape.expected_loss_ratio)
    np.testing.assert_allclose(group.cape_cod["incurred"].ultimate, cape.ultimate)
    np.testing.assert_allclose(group.bornhuetter_ferguson["incurred"].ultimate, direct.ultimate)
    # the prior is the Cape Cod ratio of the same triangle, labelled data-derived (record 0011)
    assert set(group.bornhuetter_ferguson["incurred"].prior_source) == {"data-derived prior"}
    expected = cape.expected_loss_ratio * PREMIUM_ARRAY
    np.testing.assert_allclose(group.expected_loss_ratio["incurred"].ultimate, expected)


def test_selection_is_made_on_incurred_with_the_maturity_rule(group) -> None:
    incurred = _array("incurred")
    chain = chain_ladder(incurred)
    bf = bornhuetter_ferguson(
        chain, PREMIUM_ARRAY, cape_cod(chain, PREMIUM_ARRAY).expected_loss_ratio
    )
    chosen = select_ultimates(chain, bf)
    np.testing.assert_allclose(group.selection.ultimate, chosen.ultimate)
    assert group.selection.method[0] is Choice.CHAIN_LADDER


def test_without_premium_the_premium_methods_say_why_and_the_selection_is_chain_ladder() -> None:
    bare = run_reserving(_set(), ChainLadderSettings(), MethodInputs())
    group = bare.groups[0]
    for results in (group.bornhuetter_ferguson, group.cape_cod, group.expected_loss_ratio):
        assert all(isinstance(r, Skipped) for r in results.values())
        assert "no premiums" in results["incurred"].reason
    np.testing.assert_allclose(group.selection.ultimate, group.chain_ladder["incurred"].ultimate)
    assert isinstance(group.inflation_adjusted, Skipped)
    notes = not_run_notes(bare)
    assert any(
        n.startswith("MT03 Bornhuetter–Ferguson did not run for 2 of 2 triangles") for n in notes
    )
    assert "MT03" not in methods_run(bare) and "MT10" in methods_run(bare)


def test_premium_by_underwriting_period_is_not_built_so_the_axis_says_so() -> None:
    inputs = MethodInputs(premium=PREMIUM, origin_axis="underwriting")
    group = run_reserving(_set(), ChainLadderSettings(), inputs).groups[0]
    assert group.bornhuetter_ferguson["paid"].reason == UNDERWRITING_PREMIUM


def test_a_register_entry_reaches_the_method_and_comes_back_with_who_when_and_why() -> None:
    entry = Assumption(
        method="MT02",
        name="tail_factor",
        scope="S/L/paid",
        value=1.1,
        who="reviewer",
        when=date(2026, 1, 5),
        why="long tail line",
    )
    register = AssumptionsRegister(entries=(entry,))
    plain = run_reserving(_set(), ChainLadderSettings(), MethodInputs(premium=PREMIUM))
    judged = run_reserving(
        _set(), ChainLadderSettings(), MethodInputs(register=register, premium=PREMIUM)
    )
    paid = judged.groups[0].chain_ladder["paid"]
    assert paid.tail_factor == 1.1
    np.testing.assert_allclose(paid.ultimate, plain.groups[0].chain_ladder["paid"].ultimate * 1.1)
    # the incurred triangle has another scope: untouched
    np.testing.assert_allclose(
        judged.groups[0].chain_ladder["incurred"].ultimate,
        plain.groups[0].chain_ladder["incurred"].ultimate,
    )
    in_force = {(a.method, a.name, a.scope, a.target): a for a in judged.assumptions()}
    used = in_force[("MT02", "tail_factor", "S/L/paid", "")]
    assert (used.value, used.default, used.who, used.when) == (1.1, 1.0, "reviewer", entry.when)
    assert in_force[("MT02", "tail_factor", "S/L/incurred", "")].who == "default"
    # a prior from the register replaces the data-derived one, and the BF ultimate follows
    prior = Assumption(
        method="MT03", name="prior_loss_ratio", scope="*", value=0.5, who="reviewer", why="plan"
    )
    own = run_reserving(
        _set(),
        ChainLadderSettings(),
        MethodInputs(register=AssumptionsRegister(entries=(prior,)), premium=PREMIUM),
    ).groups[0]
    assert set(own.bornhuetter_ferguson["incurred"].prior_source) == {"user"}
    np.testing.assert_allclose(own.bornhuetter_ferguson["incurred"].prior_loss_ratio, 0.5)


def test_diagnostics_are_data_with_thin_evidence_said_once_per_group(group) -> None:
    thin = [d for d in group.diagnostics if d.item.code == "THIN_EVIDENCE"]
    assert len(thin) == 1 and thin[0].measure == ""
    assert "MT02" in thin[0].item.method and "MT10" in thin[0].item.method
    # paid 36 to 48 is 220 / 200 = 1.1, above 1.05 with tail 1.0
    late = [d for d in group.diagnostics if d.item.code == "LATE_DEVELOPMENT"]
    assert [(d.measure, d.item.target) for d in late] == [("paid", "36-48")]
    assert any(d.item.code == "FEW_LINK_RATIOS" for d in group.diagnostics)


def test_the_earlier_triangle_is_what_was_known_at_the_earlier_valuation() -> None:
    triangle = truncate_triangle(_triangle("incurred"), V0)
    assert triangle is not None
    assert triangle.origins == ("2021", "2022", "2023") and triangle.ages == (12, 24, 36)
    expected = np.array([[200, 250, 275], [220, 260, np.nan], [180, np.nan, np.nan]], dtype=float)
    np.testing.assert_array_equal(triangle.cumulative, expected)
    assert triangle.valuation_points == POINTS[:3]
    assert truncate_triangle(_triangle("incurred"), date(2023, 6, 30)) is None


def test_the_port_hands_the_selection_to_the_measures(result) -> None:
    port = ReservingPort(result, BASIS)
    selection = port.selection(CUT_OFF, BASIS)
    assert isinstance(selection, Selection)
    ultimates = result.groups[0].selection.ultimate
    assert [selection.ultimates[("S", "L", y)] for y in YEARS] == pytest.approx(list(ultimates))
    assert set(selection.cdfs) == {("paid", "S", "L"), ("incurred", "S", "L")}
    chain = result.groups[0].chain_ladder["incurred"]
    assert selection.cdfs[("incurred", "S", "L")][12] == pytest.approx(chain.cdf[0])
    assert {"MT03", "MT10"} <= port.built()


def test_the_port_refuses_another_basis_instead_of_mixing(result) -> None:
    port = ReservingPort(result, BASIS)
    other = "NET, REPORTING, NOMINAL"
    assert isinstance(port.selection(CUT_OFF, other), NotAvailable)
    answer = port.measure("RS02", other)
    assert isinstance(answer, NotAvailable) and "not on NET" in answer.reason
    assert isinstance(port.measure("RS09"), NotAvailable)


def test_the_selection_at_the_earlier_valuation_is_recomputed_on_the_earlier_data(result) -> None:
    port = ReservingPort(result, BASIS)
    earlier = port.selection(V0, BASIS)
    assert isinstance(earlier, Selection)
    incurred = np.array([[200, 250, 275], [220, 260, np.nan], [180, np.nan, np.nan]])
    chain = chain_ladder(incurred)
    cape = cape_cod(chain, PREMIUM_ARRAY[:3])
    bf = bornhuetter_ferguson(chain, PREMIUM_ARRAY[:3], cape.expected_loss_ratio)
    chosen = select_ultimates(chain, bf)
    assert [earlier.ultimates[("S", "L", y)] for y in YEARS[:3]] == pytest.approx(
        list(chosen.ultimate)
    )
    assert ("S", "L", "2024") not in earlier.ultimates  # the origin had not started
    # ages beyond the earlier triangle are beyond its pattern: the tail factor
    assert earlier.cdfs[("incurred", "S", "L")][48] == 1.0
    assert port.selection(date(2023, 6, 30), BASIS).reason.startswith("2023-06-30 is not on")  # type: ignore[union-attr]


def test_actual_versus_expected_covers_every_origin_that_had_started(result) -> None:
    """Worked by hand on incurred. At 2023-12-31 the factors are 12-24: (250 + 260) / (200 + 220)
    = 1.2143 and 24-36: 275 / 250 = 1.1, tail 1, so CDF 1.3357, 1.1, 1, 1.
    2021 (36 to 48): E = 0. 2022 (24 to 36): U = 286, E = 286 (1 - 1/1.1) = 26, A = 286 - 260 = 26.
    2023 (12 to 24): U = 180 x 1.3357 = 240.43, E = 240.43 (1/1.1 - 1/1.3357) = 38.571, A = 30.
    Only the oldest origin was compared before the origin's own age was used."""
    inputs = make_inputs(
        {"claim_valuations": [cv(12)]},
        cut_off=CUT_OFF,
        triangles=_set(),
        methods=ReservingPort(result, BASIS),
    )
    frame = measure(inputs, "AE01", "origin_period").frame
    incurred = {
        r["origin_period"]: r
        for r in frame.filter(pl.col("measure") == "incurred").iter_rows(named=True)
    }
    assert set(incurred) == {"2021", "2022", "2023"}
    assert incurred["2021"]["denominator"] == pytest.approx(0.0)
    assert (incurred["2022"]["numerator"], incurred["2022"]["denominator"]) == pytest.approx(
        (26.0, 26.0)
    )
    assert incurred["2022"]["value"] == pytest.approx(1.0)
    assert (incurred["2023"]["numerator"], incurred["2023"]["denominator"]) == pytest.approx(
        (30.0, 180 * 510 / 420 - 180)
    )
    assert incurred["2023"]["value"] == pytest.approx(30 / (180 * 510 / 420 - 180))


def test_the_ultimate_ratios_and_the_tables_come_through_the_port(result) -> None:
    inputs = make_inputs(
        {"claim_valuations": [cv(12)]},
        cut_off=CUT_OFF,
        triangles=_set(),
        methods=ReservingPort(result, BASIS),
    )
    for measure_id in ("RS01", "RS02", "RS03"):
        found = measure(inputs, measure_id)
        assert found.available or "Mack" in found.reason or "did not" in found.reason
    rs01 = measure(inputs, "RS01").frame
    column = rs01.filter(
        (pl.col("measure") == "incurred") & (pl.col("development_period") == "12-24")
    )
    assert column["selected_factor"][0] == pytest.approx(720 / 600)  # three origins
    assert column["link_ratios_used"][0] == 3
    rs02 = measure(inputs, "RS02").frame
    selected = rs02.filter(pl.col("method") == "selected").sort("origin_period")
    assert selected["ultimate"].to_list() == pytest.approx(
        list(result.groups[0].selection.ultimate)
    )
    # the incurred chain ladder's IBNR is its ultimate minus the incurred to date
    chain = rs02.filter((pl.col("method") == "chain_ladder") & (pl.col("measure") == "incurred"))
    assert chain.sort("origin_period")["ibnr"].to_list() == pytest.approx(
        list(
            result.groups[0].chain_ladder["incurred"].ultimate
            - _array("incurred")[[0, 1, 2, 3], [3, 2, 1, 0]]
        )
    )
