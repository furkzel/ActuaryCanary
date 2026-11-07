# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false
# pyright: reportCallIssue=false, reportIndexIssue=false, reportOptionalOperand=false
"""Uncertainty and risk (M12), records 0323 to 0329. Spec IDs proved: M12, RS03, RS04, RS05, CV10.

The triangles are the RAA benchmark (ten origins) as in test_tier_b_wiring, in one line and in two.
The risk figures themselves are proved in tests/measures; these tests prove the wiring: which
reserve is ranged, how the simulations are scaled to the selected unpaid, the expected cash flows
and their present value against hand arithmetic, the lines added, and what is said when something
cannot be shown.
"""

from dataclasses import replace
from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.discount import DiscountSettings, resolve_discount
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.measures.port import NotAvailable
from actuarycanary.measures.risk import sample_risk
from actuarycanary.methods.assumptions import Assumption, AssumptionError, AssumptionsRegister
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.mack import PERCENTILES, TVAR_LEVEL, VAR_LEVEL
from actuarycanary.methods.selection import Selection
from actuarycanary.modules.methods_port import ReservingPort, range_table
from actuarycanary.modules.reserving import ChainLadderSettings, MethodInputs, run_reserving
from actuarycanary.modules.uncertainty import (
    ALL_LINES,
    BOOTSTRAP_SOURCE,
    EXPECTED_SOURCE,
    MACK_SOURCE,
    UncertaintyResult,
    line_correlation,
    run_uncertainty,
)
from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.modules.test_tier_b_wiring import (
    _premium,
    _source,
    _triangles,
)

CUT_OFF = date(2009, 12, 31)
SIMULATIONS = 200
LEVELS = (PERCENTILES, VAR_LEVEL, TVAR_LEVEL)


def _register(*groups: str, **extra: float) -> AssumptionsRegister:
    entries = [
        Assumption(
            method="MT11",
            name="n_simulations",
            scope=f"{group}/paid",
            value=SIMULATIONS,
            who="test",
            why="keep the test fast",
        )
        for group in groups
    ]
    entries += [
        Assumption(method="RS05", name=name, value=value, who="test", why="test")
        for name, value in extra.items()
    ]
    return AssumptionsRegister(entries=tuple(entries))


def _two_lines() -> TriangleSet:
    paid, incurred = _triangles()
    other = tuple(
        replace(t, group=("S", "L2"), cumulative=t.cumulative * 0.5) for t in (paid, incurred)
    )
    return TriangleSet(
        TriangleSettings(), "TRY", CUT_OFF, "accident", 0, 55, (paid, incurred, *other),
        pl.DataFrame(), (),
    )  # fmt: skip


def _premium_two() -> pl.DataFrame:
    first = _premium()
    return pl.concat([first, first.with_columns(pl.lit("L2").alias("line"))])


@pytest.fixture(scope="module")
def reserving():
    inputs = MethodInputs(
        premium=_premium_two(), register=_register("S/L", "S/L2"), tier_b=_source()
    )
    return run_reserving(_two_lines(), ChainLadderSettings(), inputs)


def rates(rate: float = 0.10, currency: str = "TRY") -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "curve_id": "C",
                "date": CUT_OFF,
                "tenor_months": months,
                "rate": rate,
                "rate_type": "SPOT",
                "compounding": "ANNUAL",
                "currency": currency,
                "source": "TEST",
                SOURCE_ROW: months,
            }
            for months in (12, 120)
        ]
    )


def context(rate: float | None = 0.10):
    if rate is None:
        return resolve_discount(DiscountSettings(), AssumptionsRegister(), None, CUT_OFF, "TRY")
    return resolve_discount(
        DiscountSettings(curve_id="C"), AssumptionsRegister(), rates(rate), CUT_OFF, "TRY"
    )


@pytest.fixture(scope="module")
def discounted(reserving) -> UncertaintyResult:
    found = run_uncertainty(reserving, context(), AssumptionsRegister())
    assert isinstance(found, UncertaintyResult)
    return found


@pytest.fixture(scope="module")
def nominal(reserving) -> UncertaintyResult:
    found = run_uncertainty(reserving, context(None), AssumptionsRegister())
    assert isinstance(found, UncertaintyResult)
    return found


def row(result: UncertaintyResult, line: str, origin: str, source: str, basis: str = "NOMINAL"):
    found = result.risk.filter(
        (pl.col("line") == line)
        & (pl.col("origin_period") == origin)
        & (pl.col("source") == source)
        & (pl.col("value_basis") == basis)
    )
    assert found.height == 1, (line, origin, source, basis, found.height)
    return found.row(0, named=True)


# --- the Mack side is RS03 -------------------------------------------------------------------


def test_the_mack_rows_are_the_rs03_rows_of_the_paid_triangle(reserving, nominal) -> None:
    table = range_table(reserving).filter(
        (pl.col("measure") == "paid")
        & (pl.col("line") == "L")
        & (pl.col("origin_period") == "Total")
    )
    expected = table.row(0, named=True)
    found = row(nominal, "L", "Total", MACK_SOURCE)
    assert found["mean"] == pytest.approx(expected["reserve_selected"], rel=1e-12)
    assert found["standard_deviation"] == pytest.approx(expected["standard_error"], rel=1e-12)
    assert found["value_at_risk"] == pytest.approx(expected["var_99_5"], rel=1e-12)
    assert found["tail_value_at_risk"] == pytest.approx(expected["tvar_99"], rel=1e-12)
    assert found["p95"] == pytest.approx(expected["p95"], rel=1e-12)
    assert "lognormal" in found["label"] and "Mack" in found["label"]


# --- the bootstrap side is RS05, scaled to the selected unpaid ---------------------------------


def test_the_selected_unpaid_is_the_selected_ultimate_minus_paid(reserving, nominal) -> None:
    group = reserving.groups[0]
    line = next(x for x in nominal.lines if x.key == ("S", "L"))
    expected = group.selection.ultimate - group.triangles["paid"].latest
    np.testing.assert_allclose(line.selected_unpaid, expected, rtol=1e-12)


def test_a_selection_other_than_the_chain_ladder_scales_each_origin_to_the_selected_unpaid(
    reserving, nominal
) -> None:
    line = next(x for x in nominal.lines if x.key == ("S", "L"))
    chain = reserving.groups[0].chain_ladder["paid"]
    assert not np.allclose(line.selected_unpaid, chain.reserve)  # the premise
    assert line.shifted
    mean = line.origin_sims.mean(axis=0)
    developed = np.abs(line.boot.reserves.mean(axis=0)) > 1e-12
    np.testing.assert_allclose(mean[developed], line.selected_unpaid[developed], rtol=1e-12)
    # the scaling is multiplicative: the coefficient of variation of each origin is kept
    raw = line.boot.reserves
    cv = raw[:, developed].std(axis=0, ddof=1) / raw[:, developed].mean(axis=0)
    scaled = line.origin_sims[:, developed]
    np.testing.assert_allclose(scaled.std(axis=0, ddof=1) / scaled.mean(axis=0), cv, rtol=1e-12)
    found = row(nominal, "L", "Total", BOOTSTRAP_SOURCE)
    assert found["label"] == "bootstrap CV applied to the selected reserve"
    # an origin with no simulated unpaid (the oldest, fully developed) stays at zero (RS05)
    assert not developed.all()
    assert found["mean"] == pytest.approx(line.selected_unpaid[developed].sum(), rel=1e-12)
    assert any("no simulated unpaid to scale" in note for note in line.notes)
    assert any("no simulated unpaid to scale" in note for note in nominal.notes)


def test_a_selection_equal_to_the_chain_ladder_keeps_the_simulations_as_they_are(reserving) -> None:
    group = reserving.groups[0]
    chain = group.chain_ladder["paid"]
    paid = group.triangles["paid"].latest
    same = replace(group.selection, ultimate=paid + chain.reserve)
    assert isinstance(same, Selection)
    alone = replace(reserving, groups=(replace(group, selection=same),))
    found = run_uncertainty(alone, context(None), AssumptionsRegister())
    line = found.lines[0]
    assert not line.shifted
    np.testing.assert_array_equal(line.origin_sims, group.tier_b.bootstrap.reserves)
    assert row(found, "L", "Total", BOOTSTRAP_SOURCE)["label"].startswith(
        "bootstrap (over-dispersed"
    )


def test_the_bootstrap_risk_figures_are_those_of_the_simulated_values(nominal) -> None:
    line = next(x for x in nominal.lines if x.key == ("S", "L"))
    expected = sample_risk(line.total_sims, *LEVELS)
    found = row(nominal, "L", "Total", BOOTSTRAP_SOURCE)
    assert found["value_at_risk"] == expected.value_at_risk
    assert found["tail_value_at_risk"] == expected.tail_value_at_risk
    assert found["simulations"] == SIMULATIONS and found["tail_count"] == expected.tail_count
    assert "mean of the simulated values at or above the quantile" in found["estimator"]
    assert found["tail_value_at_risk"] >= found["value_at_risk"] or TVAR_LEVEL < VAR_LEVEL
    assert found["p50"] == pytest.approx(float(np.quantile(line.total_sims, 0.5)))


def test_the_simulation_count_is_the_one_of_the_bootstrap(reserving, nominal) -> None:
    assert row(nominal, "L", "Total", BOOTSTRAP_SOURCE)["simulations"] == SIMULATIONS
    assert nominal.distribution.height == SIMULATIONS


# --- expected cash flows and their present value (RS04, CV10) ---------------------------------


def test_the_expected_flows_of_each_origin_add_to_its_selected_unpaid(nominal) -> None:
    for line in nominal.lines:
        np.testing.assert_allclose(
            line.flows.sum(axis=1), line.selected_unpaid, rtol=1e-10, atol=1e-8
        )


def test_the_expected_flows_follow_the_paid_chain_ladder_pattern(reserving, nominal) -> None:
    group = reserving.groups[0]
    chain = group.chain_ladder["paid"]
    line = next(x for x in nominal.lines if x.key == ("S", "L"))
    i = len(chain.latest) - 1  # the youngest origin: all columns still to come
    ultimate = chain.latest[i] * chain.cdf[0]
    pattern = ultimate * (1 / chain.cdf[1:] - 1 / chain.cdf[:-1])
    scale = line.selected_unpaid[i] / chain.reserve[i]
    np.testing.assert_allclose(line.flows[i, : len(pattern)], pattern * scale, rtol=1e-10)


def test_the_present_value_is_the_flows_times_one_over_one_point_one_to_the_t(
    reserving, discounted
) -> None:
    line = next(x for x in discounted.lines if x.key == ("S", "L"))
    expected = np.zeros(len(line.origins))
    for s in range(line.flows.shape[1]):
        start, end = date(2009 + s, 12, 31), date(2010 + s, 12, 31)
        paid_on = start.toordinal() + (end - start).days // 2
        years = (paid_on - CUT_OFF.toordinal()) / 365.25
        expected += line.flows[:, s] / 1.1**years
    found = row(discounted, "L", "Total", EXPECTED_SOURCE, "DISCOUNTED")
    assert found["mean"] == pytest.approx(expected.sum(), rel=1e-12)
    assert found["nominal_mean"] == pytest.approx(line.selected_total, rel=1e-12)
    assert found["discount_effect"] == pytest.approx(
        line.selected_total - expected.sum(), rel=1e-12
    )
    for i, origin in enumerate(line.origins):
        assert row(discounted, "L", origin, EXPECTED_SOURCE, "DISCOUNTED")["mean"] == pytest.approx(
            expected[i], rel=1e-12
        )


def test_a_zero_rate_curve_discounts_nothing(reserving) -> None:
    found = run_uncertainty(reserving, context(0.0), AssumptionsRegister())
    line = found.lines[0]
    np.testing.assert_allclose(line.discount_factors, 1.0, atol=1e-15)
    np.testing.assert_allclose(line.discounted_sims, line.total_sims, rtol=1e-12)
    assert row(found, "L", "Total", EXPECTED_SOURCE, "DISCOUNTED")[
        "discount_effect"
    ] == pytest.approx(0.0, abs=1e-6)


def test_each_simulation_is_discounted_by_the_share_its_own_cash_flows_keep(discounted) -> None:
    line = next(x for x in discounted.lines if x.key == ("S", "L"))
    raw = line.boot.cash_flows
    factors = line.discount_factors[: raw.shape[1]]
    share = (raw @ factors) / raw.sum(axis=1)
    assert np.all(raw.sum(axis=1) > 0)  # the premise: no fallback to the ratio of the means
    share = np.clip(share, factors.min(), factors.max())  # a share never leaves the factors
    np.testing.assert_allclose(line.discounted_sims, line.total_sims * share, rtol=1e-12)
    positive = line.total_sims > 0
    assert np.all(line.discounted_sims[positive] < line.total_sims[positive])
    # the simulated cash flows keep the mean of the scaled reserve
    assert line.cash_flow_sims.sum(axis=1).mean() == pytest.approx(
        line.total_sims.mean(), rel=1e-12
    )
    nominal_row = row(discounted, "L", "Total", BOOTSTRAP_SOURCE)
    present = row(discounted, "L", "Total", BOOTSTRAP_SOURCE, "DISCOUNTED")
    assert present["nominal_mean"] == pytest.approx(nominal_row["mean"], rel=1e-12)
    assert present["mean"] < nominal_row["mean"]
    assert present["note"] == "curve C of 2009-12-31"


def test_the_cash_flow_table_has_the_curve_the_factors_and_the_percentiles(discounted) -> None:
    table = discounted.cash_flows.filter(pl.col("line") == "L")
    first = table.row(0, named=True)
    assert first["period"] == 1 and first["end"] == date(2010, 12, 31)
    years = (first["payment_date"] - CUT_OFF).days / 365.25
    assert first["years"] == pytest.approx(years) and first["discount_factor"] == pytest.approx(
        1.1**-years
    )
    assert first["expected_discounted"] == pytest.approx(
        first["expected_nominal"] * first["discount_factor"], rel=1e-12
    )
    assert first["discounted_p95"] == pytest.approx(
        first["bootstrap_p95"] * first["discount_factor"]
    )
    assert table["expected_nominal"].sum() == pytest.approx(
        sum(x.selected_total for x in discounted.lines if x.key == ("S", "L")), rel=1e-10
    )


def test_the_curve_used_is_written_with_its_id_and_date(discounted, nominal) -> None:
    assert discounted.curve["curve_id"].unique().to_list() == ["C"]
    assert discounted.curve["curve_date"].unique().to_list() == [CUT_OFF]
    assert nominal.curve.height == 0
    assert nominal.risk.filter(pl.col("value_basis") == "DISCOUNTED").height == 0
    assert nominal.cash_flows["discount_factor"].null_count() == nominal.cash_flows.height


# --- the lines added ---------------------------------------------------------------------------


def test_the_selected_reserves_of_the_lines_add_in_the_mack_total(nominal) -> None:
    first, second = (row(nominal, name, "Total", MACK_SOURCE) for name in ("L", "L2"))
    total = row(nominal, ALL_LINES, "Total", MACK_SOURCE)
    assert total["mean"] == pytest.approx(first["mean"] + second["mean"], rel=1e-12)
    independent = np.hypot(first["standard_deviation"], second["standard_deviation"])
    assert total["standard_deviation"] == pytest.approx(independent, rel=1e-12)
    assert "correlation 0" in total["label"]


def test_independent_lines_add_simulation_by_simulation(nominal) -> None:
    first, second = (next(x for x in nominal.lines if x.key[1] == n) for n in ("L", "L2"))
    total = nominal.distribution[ALL_LINES].to_numpy()
    np.testing.assert_array_equal(total, first.total_sims + second.total_sims)
    found = row(nominal, ALL_LINES, "Total", BOOTSTRAP_SOURCE)
    assert found["mean"] == pytest.approx(total.mean(), rel=1e-12)
    assert found["value_at_risk"] == sample_risk(total, *LEVELS).value_at_risk


def test_a_correlation_in_the_register_widens_the_total_and_is_in_force(reserving) -> None:
    register = _register(**{"line_correlation": 1.0})
    found = run_uncertainty(reserving, context(None), register)
    assert found.correlation == 1.0
    wide = row(found, ALL_LINES, "Total", MACK_SOURCE)
    parts = [row(found, n, "Total", MACK_SOURCE)["standard_deviation"] for n in ("L", "L2")]
    assert wide["standard_deviation"] == pytest.approx(sum(parts), rel=1e-12)
    together = found.distribution[ALL_LINES].to_numpy()
    first, second = (x.total_sims for x in found.lines)
    # perfectly correlated lines pair the values by size
    np.testing.assert_allclose(np.sort(together), np.sort(first) + np.sort(second), rtol=1e-12)
    assert together.std() > (first + second).std()
    entry = line_correlation(register)[1]
    assert (entry.method, entry.name, entry.value, entry.who) == (
        "RS05",
        "line_correlation",
        1.0,
        "test",
    )
    default = line_correlation(AssumptionsRegister())[1]
    assert default.value == 0.0 and default.who == "default"
    with pytest.raises(AssumptionError, match="0 to 1"):
        line_correlation(_register(**{"line_correlation": 1.5}))


def test_no_simulated_total_when_a_line_has_no_bootstrap_and_the_line_is_named(reserving) -> None:
    second = reserving.groups[1]
    broken = replace(second, tier_b=replace(second.tier_b, bootstrap=Skipped("MT11", "test")))
    partial = replace(reserving, groups=(reserving.groups[0], broken))
    found = run_uncertainty(partial, context(None), AssumptionsRegister())
    assert ALL_LINES not in found.distribution.columns
    assert row(found, "L", "Total", BOOTSTRAP_SOURCE)  # the line that has one is still shown
    assert (
        found.risk.filter((pl.col("line") == "L2") & (pl.col("source") == BOOTSTRAP_SOURCE)).height
        == 0
    )
    assert any("S / L2" in note and "bootstrap did not run" in note for note in found.notes)
    assert (
        found.risk.filter(
            (pl.col("line") == ALL_LINES) & (pl.col("source") == BOOTSTRAP_SOURCE)
        ).height
        == 0
    )
    assert row(found, ALL_LINES, "Total", MACK_SOURCE)  # the Mack total needs no simulation


# --- what is said when something cannot be shown -----------------------------------------------


def test_a_run_without_bootstrap_still_gives_mack_and_the_expected_flows(reserving) -> None:
    bare = tuple(replace(g, tier_b=None) for g in reserving.groups)
    found = run_uncertainty(replace(reserving, groups=bare), context(), AssumptionsRegister())
    assert found.distribution.width == 0
    assert row(found, "L", "Total", MACK_SOURCE) and row(
        found, "L", "Total", EXPECTED_SOURCE, "DISCOUNTED"
    )
    assert found.risk.filter(pl.col("source") == BOOTSTRAP_SOURCE).height == 0
    assert any("MT11 did not run" in note for note in found.notes)


def test_nothing_to_range_gives_the_reason_as_text(reserving) -> None:
    empty = replace(
        reserving,
        groups=tuple(
            replace(g, selection=None, chain_ladder={"paid": Skipped("MT02", "x")})
            for g in reserving.groups
        ),
    )
    reason = run_uncertainty(empty, context(), AssumptionsRegister())
    assert isinstance(reason, str) and "paid chain ladder did not run" in reason


# --- the measures through the port -------------------------------------------------------------


def port(result, basis: str = "GROSS, REPORTING, NOMINAL"):
    return ReservingPort(None, basis, uncertainty=result)


def test_rs04_exists_on_the_discounted_basis_only_and_rs05_on_both(discounted, nominal) -> None:
    on = port(discounted)
    rs04 = on.measure("RS04", "GROSS, REPORTING, DISCOUNTED")
    assert isinstance(rs04, pl.DataFrame) and set(rs04["source"].unique()) == {EXPECTED_SOURCE}
    assert {"mean", "nominal_mean", "discount_effect"} <= set(rs04.columns)
    both = [on.measure("RS05", f"GROSS, REPORTING, {v}") for v in ("NOMINAL", "DISCOUNTED")]
    assert all(isinstance(t, pl.DataFrame) for t in both)
    assert set(both[0]["value_basis"]) == {"NOMINAL"} and set(both[1]["value_basis"]) == {
        "DISCOUNTED"
    }
    # the discounted distribution is for a line and for all lines, not for an origin
    assert set(both[1]["origin_period"]) == {"Total"}


def test_without_a_curve_the_discounted_figures_are_not_available_and_say_why(nominal) -> None:
    off = port(nominal).measure("RS04", "GROSS, REPORTING, DISCOUNTED")
    assert isinstance(off, NotAvailable) and "no curve is named" in off.reason
    rs05 = port(nominal).measure("RS05", "GROSS, REPORTING, DISCOUNTED")
    assert isinstance(rs05, NotAvailable) and "no curve is named" in rs05.reason
    assert isinstance(port(nominal).measure("RS05", "GROSS, REPORTING, NOMINAL"), pl.DataFrame)


def test_another_reinsurance_basis_than_the_run_is_not_available(discounted) -> None:
    other = port(discounted).measure("RS05", "NET, REPORTING, NOMINAL")
    assert isinstance(other, NotAvailable) and "not on NET" in other.reason


def test_a_module_that_gave_a_reason_has_no_tables() -> None:
    off = port("no line could be developed").measure("RS05", "GROSS, REPORTING, NOMINAL")
    assert isinstance(off, NotAvailable) and off.reason == "no line could be developed"
    missing = ReservingPort(None, "GROSS, REPORTING, NOMINAL").measure("RS04", "")
    assert isinstance(missing, NotAvailable) and "did not run" in missing.reason


def test_the_triangles_helper_is_the_raa_benchmark() -> None:
    paid, incurred = _triangles()
    assert isinstance(paid, Triangle) and len(paid.origins) == 10
    assert incurred.cumulative[0, -1] == pytest.approx(1.2 * paid.cumulative[0, -1])
