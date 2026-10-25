"""MT22 back-testing of past selections: hand fixture, the as-of rule (equal to a run on the input
known at the past cut-off), runners, range calibration, AE01 beside the errors, failure modes."""

from datetime import date

import numpy as np
import pytest

from actuarycanary.methods.back_testing import (
    ACTUAL,
    TODAY,
    AsOf,
    BackTest,
    as_of,
    back_test,
    chain_ladder_runner,
    premium_runners,
)
from actuarycanary.methods.chain_ladder import Skipped, chain_ladder
from actuarycanary.methods.seeding import generator
from actuarycanary.modules.reserving import truncate_triangle
from actuarycanary.structures.triangles import Triangle, TriangleSettings, build_triangles
from tests.methods.helpers import HAND, array, fitted
from tests.methods.tier_b import series, table, triangle, value
from tests.structures.test_mt01_triangles import GROUP, TRY, _claims, _valuations

HAND_REF = "MT22-back-test-four-origins"


def _calendar(cumulative: np.ndarray) -> np.ndarray:
    n_origins, n_dev = cumulative.shape
    return np.where(~np.isnan(cumulative), np.add.outer(np.arange(n_origins), np.arange(n_dev)), -1)


def test_hand_fixture_errors_bias_mae_rmse() -> None:
    reference = np.array([float(r["reference_ultimate"]) for r in table(HAND_REF, "reference.csv")])
    estimates = {}
    for row in table(HAND_REF, "estimates.csv"):
        method = {"chain_ladder": "MT02", "bornhuetter_ferguson": "MT03"}[row["method"]]
        estimates[(method, int(row["horizon_months"]))] = np.array(
            [float(row[f"u_{o}"]) for o in (2021, 2022, 2023, 2024)]
        )
    dummy = np.full((4, 4), np.nan)  # no runner: the estimates are given
    result = back_test(
        dummy, _calendar(dummy), ["2021", "2022", "2023", "2024"], reference, np.ones(4),
        runners={}, horizons_months=(), estimates=estimates, ranges=False,
    )  # fmt: skip
    names = {"MT02": "chain_ladder", "MT03": "bornhuetter_ferguson"}
    for s in result.summaries:
        label = f"{names[s.method]}_h{s.horizon_months}"
        assert s.bias == pytest.approx(
            value(HAND_REF, f"bias_{label}", "all"), rel=1e-12, abs=1e-15
        )
        assert s.mean_absolute_error == pytest.approx(
            value(HAND_REF, f"mae_{label}", "all"), rel=1e-12
        )
        assert s.root_mean_square_error == pytest.approx(
            value(HAND_REF, f"rmse_{label}", "all"), rel=1e-12
        )
        assert s.origins == 4
    for method, h in estimates:
        errors = [e.error for e in result.errors if e.method == method and e.horizon_months == h]
        np.testing.assert_allclose(
            errors, series(HAND_REF, f"error_{names[method]}_h{h}"), rtol=1e-12, atol=1e-15
        )
    assert len(result.summaries) == 4 and {e.label for e in result.errors} == {ACTUAL}


def _hand_triangle() -> Triangle:
    cumulative = array(HAND["incurred"])
    points = tuple(date(y, 12, 31) for y in (2021, 2022, 2023, 2024))
    return Triangle(
        "incurred", ("S", "L"), ("2021", "2022", "2023", "2024"), (12, 24, 36, 48), cumulative,
        np.where(np.isfinite(cumulative), 5, -1), _calendar(cumulative), points,
    )  # fmt: skip


@pytest.mark.parametrize("steps", [1, 2, 3])
def test_as_of_cut_is_the_cut_of_the_reserving_module(steps: int) -> None:
    tri = _hand_triangle()
    cut = as_of(tri.cumulative, tri.calendar, steps)
    earlier = truncate_triangle(tri, tri.valuation_points[-1 - steps])
    assert isinstance(cut, AsOf) and earlier is not None
    np.testing.assert_array_equal(cut.cumulative, earlier.cumulative)
    np.testing.assert_array_equal(cut.calendar, earlier.calendar)
    assert tuple(np.array(tri.origins)[cut.rows]) == earlier.origins
    assert as_of(tri.cumulative, tri.calendar, 4) is None


def test_rerun_at_the_past_cut_off_equals_a_run_on_the_input_known_then() -> None:
    today = build_triangles(_valuations(), _claims(), TriangleSettings(), TRY, "TRY")
    then = build_triangles(
        _valuations(), _claims(), TriangleSettings(cut_off=date(2024, 6, 30)), TRY, "TRY"
    )
    for measure in ("paid", "incurred"):
        now, past = today.get(measure, GROUP), then.get(measure, GROUP)
        cut = as_of(now.cumulative, now.calendar, 1)
        assert cut is not None
        np.testing.assert_array_equal(cut.cumulative, past.cumulative)
        np.testing.assert_array_equal(cut.calendar, past.calendar)
        assert tuple(np.array(now.origins)[cut.rows]) == past.origins
        rerun = chain_ladder_runner(cut.cumulative, cut.calendar, cut.rows)
        direct = chain_ladder(past.cumulative, calendar=past.calendar, min_origins=1)
        if isinstance(rerun, Skipped):  # two origins: fewer than MT02's three
            assert rerun.reason == "chain ladder needs at least 3 origin periods"
        else:
            assert not isinstance(direct, Skipped)
            np.testing.assert_array_equal(rerun, direct.ultimate)


def _genins() -> tuple[np.ndarray, list[str]]:
    tri, origins, _ = triangle("MT13-benktander-genins")
    return tri, origins


def test_runners_at_three_horizons_with_ranges_and_actual_versus_expected() -> None:
    tri, origins = _genins()
    chain = fitted(tri)
    premium = np.full(len(origins), 6e6)
    runners = {"MT02": chain_ladder_runner, **premium_runners(premium)}
    result = back_test(
        tri, _calendar(tri), origins, chain.ultimate, 1 / chain.cdf_at_latest,
        runners=runners, bootstrap_rng=generator(1, "test"), backtest_simulations=200,
    )  # fmt: skip
    assert isinstance(result, BackTest) and result.horizons_not_computed == {}
    assert {(s.method, s.horizon_months) for s in result.summaries} == {
        (m, h) for m in ("MT02", "MT03", "MT04", "MT05", "MT10") for h in (12, 24, 36)
    }
    cut = as_of(tri, _calendar(tri), 1)
    assert cut is not None
    expected = fitted(cut.cumulative).ultimate
    run_off = result.run_off("MT02")
    assert [run_off[o][12] for o in origins[:9]] == pytest.approx(list(expected), rel=1e-12)
    assert "2010" not in run_off  # the newest origin had not started a year earlier
    assert {e.label for e in result.errors} == {ACTUAL, TODAY}
    by_method = {(r.method, r.horizon_months): r for r in result.ranges}
    assert set(by_method) == {(m, h) for m in ("MT06", "MT11") for h in (12, 24, 36)}
    assert all(0 < r.origins <= 9 and 0 <= r.share <= 1 for r in result.ranges)
    # AE01 over 12 months for 2008: development seen against what the 2008 pattern expected
    seen = next(
        a for a in result.actual_versus_expected if a.horizon_months == 12 and a.origin == "2008"
    )
    past = fitted(cut.cumulative)
    assert seen.actual == pytest.approx(tri[7, 2] - tri[7, 1], rel=1e-12)
    assert seen.expected == pytest.approx(
        past.ultimate[7] * (1 / past.cdf[2] - 1 / past.cdf[1]), rel=1e-12
    )


def _any_size(cumulative: np.ndarray, calendar: np.ndarray, rows: np.ndarray) -> np.ndarray:
    found = chain_ladder(cumulative, calendar=calendar, min_origins=1)
    assert not isinstance(found, Skipped)
    return found.ultimate


def test_failure_modes() -> None:
    tri, origins = _genins()
    chain = fitted(tri)
    options = {"origins": origins, "reference": chain.ultimate, "ranges": False}
    result = back_test(
        tri, _calendar(tri), reported_share=1 / chain.cdf_at_latest,
        runners={"MT02": chain_ladder_runner, "small": _any_size}, horizons_months=(18, 96, 120),
        **options,
    )  # fmt: skip
    assert "whole number of development periods" in result.horizons_not_computed[18]
    assert "nothing was known" in result.horizons_not_computed[120]
    assert result.not_run == {("MT02", 96): "chain ladder needs at least 3 origin periods"}
    assert [(n.method, n.reason) for n in result.not_summarised] == [
        ("small", "only 2 origins with a reference (fewer than 3)")
    ]
    assert result.summaries == ()
    failing = back_test(
        tri, _calendar(tri), reported_share=np.ones(10), horizons_months=(12,),
        runners={"MT04": premium_runners(np.full(10, np.nan))["MT04"]}, **options,
    )  # fmt: skip
    assert failing.not_run == {("MT04", 12): "no origin with positive earned premium"}
    zero = chain.ultimate.copy()
    zero[0] = 0.0
    found = back_test(
        tri, _calendar(tri), origins, zero, np.ones(10), horizons_months=(12,), ranges=False
    )
    assert "2001" not in {e.origin for e in found.errors}
