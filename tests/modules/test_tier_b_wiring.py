# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false
"""The tier B methods wired into the reserving module (M04), record 0620.

Spec IDs proved: MT11, MT12, MT13, MT14, MT15, MT16, MT22, AE02. The methods are proved against
their fixtures and references in tests/methods; these tests prove the wiring: the right
triangle, the right stream and parameters reach each method, tier A does not move, a method
that cannot run keeps its reason, and the entries in force come back. The triangles are the
RAA benchmark (ten origins) with a made-up incurred triangle 1.2 times the paid one.
"""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.methods.assumptions import Assumption, AssumptionError, AssumptionsRegister
from actuarycanary.methods.back_testing import back_test, chain_ladder_runner, premium_runners
from actuarycanary.methods.benktander import Benktander, benktander
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.munich import Munich, munich_chain_ladder
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, odp_bootstrap
from actuarycanary.methods.seeding import generator
from actuarycanary.methods.tail import TailFit, fit_tail
from actuarycanary.modules.reserving import (
    ChainLadderSettings,
    MethodInputs,
    methods_run,
    not_run_notes,
    run_reserving,
)
from actuarycanary.modules.reserving_tier_b_output import (
    ae02_table,
    back_test_table,
    bootstrap_summary,
    distribution_files,
    measures_run,
    parameters_table,
    tables,
    ultimates_table,
)
from actuarycanary.modules.tier_b_inputs import NO_CLAIMS, TierBInputs, tier_b_source
from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.methods.tier_b import triangle

GROUP = ("S", "L")
SIMULATIONS = 100


def _triangles() -> tuple[Triangle, Triangle]:
    paid, origins, ages = triangle("MT11-odp-bootstrap-raa")
    n = len(origins)
    observed = ~np.isnan(paid)
    calendar = np.where(observed, np.add.outer(np.arange(n), np.arange(n)), -1)
    points = tuple(date(2000 + i, 12, 31) for i in range(n))
    counts = np.where(observed, 5, -1)
    return tuple(  # type: ignore[return-value]
        Triangle(m, GROUP, tuple(origins), tuple(ages), cumulative, counts, calendar, points)
        for m, cumulative in (("paid", paid), ("incurred", paid * 1.2))
    )


def _set() -> TriangleSet:
    paid, incurred = _triangles()
    return TriangleSet(
        TriangleSettings(), "TRY", paid.valuation_points[-1], "accident", 0, 55,
        (paid, incurred), pl.DataFrame(), (),
    )  # fmt: skip


def _premium(factor: float = 1.0) -> pl.DataFrame:
    paid, _ = _triangles()
    return pl.DataFrame(
        {
            "segment": ["S"] * len(paid.origins),
            "line": ["L"] * len(paid.origins),
            "origin_period": list(paid.origins),
            "earned_premium": [
                factor * 100_000.0 * (1 + 0.02 * i) for i in range(len(paid.origins))
            ],
        }
    )


def _source() -> TierBInputs:
    """Tier B inputs without claims: MT15 and MT16 cannot run and say so."""
    source = tier_b_source(
        pl.DataFrame(), None, None, TriangleSettings(), {}, "TRY",  # type: ignore[arg-type]
        policies=None, market=None, price_index="CPI_TR", cut_off=date(2009, 12, 31),
    )  # fmt: skip
    return TierBInputs(source)


def _register(n: int = SIMULATIONS) -> AssumptionsRegister:
    entries = [
        Assumption(method="MT11", name="n_simulations", scope="S/L/paid", value=n,
                   who="test", why="keep the test fast"),
        Assumption(method="MT22", name="backtest_simulations", scope="S/L/incurred",
                   value=n, who="test", why="keep the test fast"),
    ]  # fmt: skip
    return AssumptionsRegister(entries=tuple(entries))


@pytest.fixture(scope="module")
def plain():
    return run_reserving(_set(), ChainLadderSettings(), MethodInputs(premium=_premium()))


@pytest.fixture(scope="module")
def wired():
    inputs = MethodInputs(premium=_premium(), register=_register(), tier_b=_source())
    return run_reserving(_set(), ChainLadderSettings(), inputs)


@pytest.fixture(scope="module")
def group(wired):
    return wired.groups[0]


def test_without_the_tier_b_inputs_no_tier_b_method_runs(plain) -> None:
    assert plain.groups[0].tier_b is None
    assert not set(methods_run(plain)) & {"MT11", "MT12", "MT13", "MT15", "MT16", "MT22"}


def test_tier_a_does_not_move_when_tier_b_runs(plain, wired) -> None:
    """The default tail of MT02 stays 1 (MT14 is fitted, not used), so every tier A result is
    the same number."""
    a, b = plain.groups[0], wired.groups[0]
    for measure in ("paid", "incurred"):
        np.testing.assert_array_equal(
            a.chain_ladder[measure].ultimate, b.chain_ladder[measure].ultimate
        )
        assert a.chain_ladder[measure].tail_factor == b.chain_ladder[measure].tail_factor == 1.0
        np.testing.assert_array_equal(
            a.bornhuetter_ferguson[measure].ultimate, b.bornhuetter_ferguson[measure].ultimate
        )
    np.testing.assert_array_equal(a.selection.ultimate, b.selection.ultimate)
    np.testing.assert_array_equal(a.mack["paid"].standard_error, b.mack["paid"].standard_error)


def test_mt11_runs_on_the_paid_triangle_from_the_stream_of_its_group(group) -> None:
    paid, _ = _triangles()
    direct = odp_bootstrap(paid.cumulative, generator(1, *GROUP), n_simulations=SIMULATIONS)
    assert isinstance(group.tier_b.bootstrap, OdpBootstrap)
    np.testing.assert_array_equal(group.tier_b.bootstrap.reserves, direct.reserves)
    assert group.tier_b.bootstrap.reserves.shape[0] == SIMULATIONS  # the register entry
    other = odp_bootstrap(paid.cumulative, generator(1, "S", "M"), n_simulations=SIMULATIONS)
    assert not np.array_equal(other.reserves, direct.reserves)  # a stream per group


def test_mt11_follows_the_mt02_tail_unless_the_user_sets_its_own() -> None:
    register = AssumptionsRegister(
        entries=(
            *_register().entries,
            Assumption(
                method="MT02",
                name="tail_factor",
                scope="S/L/paid",
                value=1.05,
                who="test",
                why="a tail",
            ),
        )  # fmt: skip
    )
    result = run_reserving(
        _set(), ChainLadderSettings(), MethodInputs(register=register, tier_b=_source())
    )
    group = result.groups[0]
    assert group.tier_b.bootstrap.tail_factor == pytest.approx(1.05)
    entry = next(e for e in group.assumptions if e.method == "MT11" and e.name == "tail_factor")
    assert entry.value == pytest.approx(1.05) and entry.who == "default"


def test_mt12_runs_on_paid_and_incurred_together(group) -> None:
    paid, incurred = _triangles()
    direct = munich_chain_ladder(
        paid.cumulative, incurred.cumulative, calendar=incurred.calendar, min_origins=5,
        ages=incurred.ages, origins=incurred.origins,
    )  # fmt: skip
    assert isinstance(group.tier_b.munich, Munich)
    np.testing.assert_array_equal(group.tier_b.munich.paid_ultimate, direct.paid_ultimate)
    np.testing.assert_array_equal(group.tier_b.munich.incurred_ultimate, direct.incurred_ultimate)


def test_mt13_blends_the_incurred_chain_ladder_with_the_bornhuetter_ferguson_prior(group) -> None:
    direct = benktander(
        group.chain_ladder["incurred"], group.bornhuetter_ferguson["incurred"], iterations=1,
        origins=group.triangles["incurred"].origins,
    )  # fmt: skip
    assert isinstance(group.tier_b.benktander, Benktander)
    np.testing.assert_array_equal(group.tier_b.benktander.ultimate, direct.ultimate)
    assert group.tier_b.benktander_measure == "incurred"


def test_mt14_is_fitted_on_every_chain_ladder_and_replaces_the_tail_only_when_selected(
    group,
) -> None:
    for measure in ("paid", "incurred"):
        fit = group.tier_b.tails[measure]
        direct = fit_tail(group.chain_ladder[measure].factors, group.triangles[measure].ages)
        assert isinstance(fit, TailFit) and isinstance(direct, TailFit)
        assert fit.chosen.tail_factor == direct.chosen.tail_factor
    chosen = group.tier_b.tails["paid"].chosen.tail_factor
    register = AssumptionsRegister(
        entries=(
            *_register(2).entries,
            Assumption(
                method="MT14",
                name="selected_curve",
                scope="S/L/paid",
                value="exponential_decay",
                who="test",
                why="long-tailed line",
            ),
        )  # fmt: skip
    )
    result = run_reserving(
        _set(), ChainLadderSettings(), MethodInputs(register=register, tier_b=_source())
    )
    assert result.groups[0].chain_ladder["paid"].tail_factor == pytest.approx(chosen)
    assert result.groups[0].chain_ladder["incurred"].tail_factor == 1.0
    tail = next(a for a in result.assumptions() if a.method == "MT02" and a.name == "tail_factor"
                and a.scope == "S/L/paid")  # fmt: skip
    assert tail.who == "test" and "MT14" in tail.why
    both = AssumptionsRegister(
        entries=(
            *register.entries,
            Assumption(
                method="MT02",
                name="tail_factor",
                scope="S/L/paid",
                value=1.02,
                who="test",
                why="two tails",
            ),
        )  # fmt: skip
    )
    with pytest.raises(AssumptionError, match="both set a tail"):
        run_reserving(_set(), ChainLadderSettings(), MethodInputs(register=both, tier_b=_source()))


def test_mt15_and_mt16_without_claims_say_so_and_never_give_a_number(wired, group) -> None:
    for outcome in (group.tier_b.separation, group.tier_b.frequency_severity):
        assert isinstance(outcome, Skipped)
        assert NO_CLAIMS in outcome.reason or "claims" in outcome.reason
    notes = " ".join(not_run_notes(wired))
    assert "MT15 separation did not run for 1 of 1 groups" in notes
    assert "MT16 frequency–severity did not run for 1 of 1 groups" in notes


def test_mt22_tests_the_incurred_triangle_against_the_selected_ultimates(group) -> None:
    incurred = group.triangles["incurred"]
    chain = group.chain_ladder["incurred"]
    runners = {"MT02": chain_ladder_runner, **premium_runners(group.premium)}
    direct = back_test(
        incurred.cumulative, incurred.calendar, incurred.origins, group.selection.ultimate,
        1 / chain.cdf_at_latest, runners=runners, horizons_months=(12, 24, 36),
        development_months=12, bootstrap_rng=generator(1, *GROUP, "MT22"),
        backtest_simulations=SIMULATIONS,
    )  # fmt: skip
    found = group.tier_b.back_test
    assert [(s.method, s.horizon_months, s.bias) for s in found.summaries] == [
        (s.method, s.horizon_months, s.bias) for s in direct.summaries
    ]
    assert {r.method for r in found.ranges} == {"MT06", "MT11"}
    assert {s.method for s in found.summaries} == {"MT02", "MT03", "MT04", "MT05", "MT10"}


def test_the_parameters_in_force_come_back_for_every_method(wired) -> None:
    in_force = {(a.method, a.name): a for a in wired.assumptions() if a.scope.startswith("S/L")}
    for method, name, value in (
        ("MT11", "n_simulations", SIMULATIONS),
        ("MT11", "process_distribution", "gamma"),
        ("MT12", "min_origins", 5),
        ("MT13", "iterations", 1),
        ("MT14", "extension_periods", 100),
        ("MT15", "trend_periods", 5),
        ("MT16", "maturity_for_trend", 0.9),
        ("MT22", "mature_at", 0.95),
        ("MT22", "backtest_simulations", SIMULATIONS),
    ):
        assert in_force[(method, name)].value == value, (method, name)
    assert in_force[("MT11", "n_simulations")].who == "test"
    assert in_force[("MT12", "min_origins")].who == "default"


def test_the_methods_that_ran_are_listed_for_the_manifest(wired) -> None:
    ran = set(methods_run(wired))
    assert {"MT11", "MT12", "MT13", "MT14", "MT22"} <= ran
    assert not ran & {"MT15", "MT16"}  # no claims: they did not run
    assert measures_run(wired) == ["AE02"]


def test_the_output_tables_have_one_row_per_origin_or_the_reason(wired) -> None:
    ultimates = ultimates_table(wired)
    methods = set(ultimates["method"])
    assert {"munich_chain_ladder", "benktander", "separation", "frequency_severity"} == methods
    reasons = ultimates.filter(pl.col("ultimate").is_null())
    assert set(reasons["method"]) == {"separation", "frequency_severity"}
    assert (reasons["origin_period"] == "").all() and (reasons["note"] != "").all()
    paid, _ = _triangles()
    assert ultimates.filter(pl.col("method") == "benktander").height == len(paid.origins)
    summary = bootstrap_summary(wired)
    assert summary.filter(pl.col("origin_period") == "Total").height == 1
    assert set(parameters_table(wired)["method"]) == {"MT11", "MT12", "MT13", "MT14"}
    assert set(tables(wired)) >= {"tier_b_ultimates.csv", "back_test.csv", "bootstrap_summary.csv"}
    files = distribution_files(wired)
    assert list(files) == ["bootstrap_distribution_S_L.parquet"]
    frame = pl.read_parquet(__import__("io").BytesIO(next(iter(files.values()))))
    assert frame.height == SIMULATIONS and frame.columns[-1] == "total"
    np.testing.assert_allclose(
        frame["total"].to_numpy(), wired.groups[0].tier_b.bootstrap.total, rtol=0, atol=0
    )


def test_ae02_is_the_error_of_the_back_test_per_method_origin_and_horizon(wired) -> None:
    table = ae02_table(wired)
    assert set(table["kind"]) == {"error", "summary"}
    summary = table.filter(pl.col("kind") == "summary").filter(
        (pl.col("method") == "MT02") & (pl.col("horizon_months") == 12)
    )
    errors = table.filter(
        (pl.col("kind") == "error")
        & (pl.col("method") == "MT02")
        & (pl.col("horizon_months") == 12)
    )
    group = wired.groups[0]
    reference = group.selection.ultimate
    weights = np.array(
        [reference[group.triangles["incurred"].origins.index(o)] for o in errors["origin_period"]]
    )
    bias = float((weights * errors["error"].to_numpy()).sum() / weights.sum())
    assert summary["bias"][0] == pytest.approx(bias, rel=1e-12)  # B = sum w e / sum w (AE02)
    assert back_test_table(wired).height > table.height  # the calibration and reasons beside
