"""The sensitivity tables of the report (record 0343): each variant reruns the methods of the
run with one assumption changed, the base is the run's own result, and the curve shift equals
discounting with the shifted curve."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.yield_curve import YieldCurve
from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.pipeline import RunResult
from actuarycanary.report import sensitivity
from actuarycanary.report.sensitivity import (
    COLUMNS,
    CURVE_STEP,
    FACTOR_STEP,
    TAIL_STEP,
    VARIANTS,
    factor_register,
    present_values,
    rerun,
    selected_ibnr,
    tail_register,
)


def test_the_steps_of_the_variants_are_settings_of_the_run(default_run: RunResult) -> None:
    manifest = default_run.manifest.read_text(encoding="utf-8")
    assert '"sensitivity"' in manifest
    assert sensitivity.settings() == {
        "factor_step": FACTOR_STEP,
        "tail_step": TAIL_STEP,
        "inflation_step": 0.01,
        "curve_step": CURVE_STEP,
    }


@pytest.mark.integration
def test_a_rerun_with_the_register_of_the_run_gives_the_run_its_own_reserve(
    default_run: RunResult,
) -> None:
    """The base of every variant is the run's selection; rerunning without a change gives it."""
    result = default_run.reserving
    again = rerun(result, result.inputs.register)
    for before, after in zip(result.groups, again.groups, strict=True):
        assert selected_ibnr(before) == pytest.approx(selected_ibnr(after), rel=1e-12)


@pytest.mark.integration
def test_the_factor_variant_moves_every_selected_factor_by_the_step(
    default_run: RunResult,
) -> None:
    result = default_run.reserving
    moved = rerun(result, factor_register(result, result.inputs.register, FACTOR_STEP))
    for before, after in zip(result.groups, moved.groups, strict=True):
        for measure in ("paid", "incurred"):
            a, b = before.chain_ladder[measure], after.chain_ladder[measure]
            if not isinstance(a, ChainLadder) or not isinstance(b, ChainLadder):
                continue
            finite = np.isfinite(a.factors)
            np.testing.assert_allclose(
                b.factors[finite] - 1, (a.factors[finite] - 1) * (1 + FACTOR_STEP), rtol=1e-12
            )


@pytest.mark.integration
def test_the_tail_variant_raises_the_tail_of_every_triangle(default_run: RunResult) -> None:
    result = default_run.reserving
    raised = rerun(result, tail_register(result, result.inputs.register, TAIL_STEP))
    for before, after in zip(result.groups, raised.groups, strict=True):
        a, b = before.chain_ladder["incurred"], after.chain_ladder["incurred"]
        if isinstance(a, ChainLadder) and isinstance(b, ChainLadder):
            assert b.tail_factor == pytest.approx(a.tail_factor + TAIL_STEP)


def test_a_parallel_shift_equals_discounting_with_the_shifted_curve() -> None:
    curve = YieldCurve(
        "C", date(2025, 12, 31), "TRY", "SPOT", "ANNUAL", "test",
        np.array([1.0, 2.0, 5.0]), np.array([0.25, 0.52, 1.4]),
    )  # fmt: skip
    years = np.array([-0.2, 0.5, 1.5, 3.0, 7.0])  # one before the discount date, one beyond
    flows = pl.DataFrame(
        {
            "segment": ["S"] * 5,
            "line": ["L"] * 5,
            "years": years,
            "discount_factor": curve.discount_factors(years),
            "expected_nominal": [5.0, 100.0, 80.0, 40.0, 10.0],
        }
    )
    shifted = YieldCurve(
        "C", date(2025, 12, 31), "TRY", "SPOT", "ANNUAL", "test",
        curve.tenors, curve.log_discount + CURVE_STEP * curve.tenors,
    )  # fmt: skip
    expected = float((flows["expected_nominal"] * shifted.discount_factors(years)).sum())
    assert present_values(flows, CURVE_STEP)[("S", "L")] == pytest.approx(expected, rel=1e-12)
    base = float((flows["expected_nominal"] * flows["discount_factor"]).sum())
    assert present_values(flows, 0.0)[("S", "L")] == pytest.approx(base, rel=1e-15)


@pytest.mark.integration
def test_every_line_has_every_variant_or_the_reason(default_run: RunResult) -> None:
    table = pl.read_csv(default_run.folder / "sensitivity.csv")
    assert tuple(table.columns) == COLUMNS
    lines = {(g.group[0], g.group[1]) for g in default_run.reserving.groups}
    for variant in VARIANTS:
        rows = table.filter(pl.col("variant") == variant.name)
        assert {(r["segment"], r["line"]) for r in rows.to_dicts()} == lines
        for r in rows.to_dicts():
            assert r["value"] is not None or r["note"], (variant.name, r)
    curve = table.filter(pl.col("variant").str.starts_with("curve"))
    assert curve["note"].str.starts_with("no discounted figures").all()  # no curve on tiny
    factors = table.filter(pl.col("variant") == "factors_up").drop_nulls("relative")
    assert (factors["relative"] > 0).all()
