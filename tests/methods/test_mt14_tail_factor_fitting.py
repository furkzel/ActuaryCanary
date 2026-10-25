"""MT14 tail factor fitting: exact curves, benchmarks, failure modes and the register selection."""

import math
from datetime import date

import numpy as np
import pytest

from actuarycanary.methods.assumptions import Assumption, AssumptionError, AssumptionsRegister
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.judgement_tier_b import chain_ladder_with_tail
from actuarycanary.methods.tail import (
    Curve,
    CurveFit,
    TailFit,
    excess,
    fit_tail,
    ultimates_with_tail,
)
from tests.methods.helpers import fitted
from tests.methods.tier_b import reference, series, triangle, value

AGES = [12 * (k + 1) for k in range(10)]


def _fit(factors, **options) -> TailFit:
    result = fit_tail(factors, AGES, **options)
    assert isinstance(result, TailFit)
    return result


def _curve(result: TailFit, curve: Curve) -> CurveFit:
    found = result.fits[curve]
    assert isinstance(found, CurveFit)
    return found


@pytest.mark.parametrize(
    ("curve", "a", "b"), [(Curve.EXPONENTIAL_DECAY, 0.7, -0.55), (Curve.INVERSE_POWER, 1.2, 2.1)]
)
def test_exact_curve_gives_back_a_b_and_the_tail_product(curve: Curve, a: float, b: float) -> None:
    x = np.arange(1, 10)
    factors = 1 + excess(curve, a, b, x)
    found = _curve(_fit(factors, curve=curve), curve)
    assert found.a == pytest.approx(a, rel=1e-9) and found.b == pytest.approx(b, rel=1e-9)
    assert found.r_squared == pytest.approx(1.0, rel=1e-12)
    product = math.prod(1 + float(excess(curve, a, b, np.array([10 + k]))[0]) for k in range(100))
    assert found.tail_factor == pytest.approx(product, rel=1e-9)
    np.testing.assert_allclose(found.fitted_factors, factors, rtol=1e-9)
    if curve is Curve.EXPONENTIAL_DECAY:  # closed form: the geometric sum of exponents
        assert math.log(found.tail_factor) == pytest.approx(
            sum(math.log1p(math.exp(a + b * (10 + k))) for k in range(100)), rel=1e-9
        )
    assert found.extension_share.sum() == pytest.approx(1 - 1 / found.tail_factor, rel=1e-9)


@pytest.mark.parametrize("name", ["raa", "genins"])
@pytest.mark.parametrize(
    ("curve", "key"),
    [(Curve.EXPONENTIAL_DECAY, "exponential"), (Curve.INVERSE_POWER, "inverse_power")],
)
def test_benchmark_against_the_package(name: str, curve: Curve, key: str) -> None:
    ref = f"MT14-tail-curves-{name}"
    tri, _, ages = triangle(ref)
    chain = fitted(tri)
    np.testing.assert_allclose(chain.factors, series(ref, "selected_factor"), rtol=1e-9)
    result = fit_tail(chain.factors, ages, curve=curve)
    assert isinstance(result, TailFit) and result.curve is curve
    found = _curve(result, curve)
    assert found.a == pytest.approx(value(ref, f"{key}_fit", "a"), rel=1e-6)
    assert found.b == pytest.approx(value(ref, f"{key}_fit", "b"), rel=1e-6)
    assert found.r_squared == pytest.approx(
        value(ref, f"{key}_fit", "r_squared_log_scale"), rel=1e-6
    )
    assert len(found.columns) == value(ref, f"{key}_fit", "n_points")
    assert found.tail_factor == pytest.approx(
        value(ref, f"{key}_tail", "package_100_periods"), rel=1e-6
    )
    assert result.tail_factor == found.tail_factor
    np.testing.assert_allclose(found.fitted_factors, series(ref, f"{key}_fitted_factor"), rtol=1e-6)


@pytest.mark.parametrize(("name", "warned"), [("raa", False), ("genins", True)])
def test_remainder_of_the_inverse_power_tail(name: str, warned: bool) -> None:
    ref = f"MT14-tail-curves-{name}"
    tri, _, ages = triangle(ref)
    result = fit_tail(fitted(tri).factors, ages)
    assert isinstance(result, TailFit)
    found = _curve(result, Curve.INVERSE_POWER)
    information = {
        (r["quantity"], r["key"]): r["value"] for r in reference(ref)["manifest"]["information"]
    }
    infinite = information[("inverse_power_tail", "infinite_product")]
    assert found.tail_remainder == pytest.approx(infinite / found.tail_factor - 1, rel=1e-6)
    assert _curve(result, Curve.EXPONENTIAL_DECAY).tail_remainder == pytest.approx(0, abs=1e-12)
    codes = [d.code for d in result.diagnostics]
    assert ("DEVELOPMENT_NOT_STOPPED" in codes) is warned


def test_too_few_factors_and_fit_range() -> None:
    assert fit_tail([1.5, 1.2, 1.0, 1.0], AGES) == Skipped(
        "MT14", "too few factors above 1 to fit a tail"
    )
    factors = 1 + excess(Curve.EXPONENTIAL_DECAY, 0.5, -0.5, np.arange(1, 10))
    late = _curve(_fit(factors, fit_from_age=48), Curve.EXPONENTIAL_DECAY)
    assert late.columns == (3, 4, 5, 6, 7, 8)
    assert isinstance(fit_tail(factors, AGES, fit_from_age=200), Skipped)


def test_wrong_slope_leaves_that_curve_out() -> None:
    rising = np.array([1.01, 1.02, 1.03, 1.05, 1.08])
    result = _fit(rising)
    assert isinstance(result.fits[Curve.EXPONENTIAL_DECAY], Skipped)
    assert isinstance(result.fits[Curve.INVERSE_POWER], Skipped)
    assert "not below 0" in result.fits[Curve.EXPONENTIAL_DECAY].reason  # type: ignore[union-attr]
    assert "diverges" in result.fits[Curve.INVERSE_POWER].reason  # type: ignore[union-attr]
    assert np.isnan(result.tail_factor)
    assert [d.code for d in result.diagnostics] == ["CURVE_NOT_USED", "CURVE_NOT_USED"]


def test_ultimates_with_tail() -> None:
    tri, _, _ = triangle("MT14-tail-curves-raa")
    chain = fitted(tri)
    np.testing.assert_allclose(ultimates_with_tail(chain, 1.05), chain.ultimate * 1.05)


def _selected(curve: str, **extra: Assumption) -> AssumptionsRegister:
    entry = Assumption(method="MT14", name="selected_curve", value=curve, who="owner",
                       when=date(2026, 10, 25), why="long-tailed line")  # fmt: skip
    return AssumptionsRegister(entries=(entry, *extra.values()))


def test_default_tail_stays_and_a_selected_curve_replaces_it() -> None:
    tri, origins, ages = triangle("MT14-tail-curves-raa")
    options = {"origins": origins, "ages": ages, "scope": "NON_LIFE/X/paid"}
    chain, fit, entries = chain_ladder_with_tail(tri, register=AssumptionsRegister(), **options)
    assert isinstance(chain, ChainLadder) and chain.tail_factor == 1.0
    assert isinstance(fit, TailFit)
    tails = [e for e in entries if e.name == "tail_factor"]
    assert len(tails) == 1 and tails[0].value == 1.0 and tails[0].is_default
    assert {e.name for e in entries if e.method == "MT14"} == {
        "curve", "fit_from_age", "min_points", "extension_periods", "remainder_warning",
    }  # fmt: skip

    chain, fit, entries = chain_ladder_with_tail(
        tri, register=_selected("inverse_power"), **options
    )
    assert isinstance(chain, ChainLadder) and isinstance(fit, TailFit)
    tau = _curve(fit, Curve.INVERSE_POWER).tail_factor
    assert chain.tail_factor == tau
    np.testing.assert_allclose(chain.ultimate, fitted(tri).ultimate * tau, rtol=1e-12)
    tail = next(e for e in entries if e.method == "MT02" and e.name == "tail_factor")
    assert tail.value == tau and tail.who == "owner" and "inverse_power" in tail.why
    assert "from 12 months" in tail.why
    assert any(e.name == "selected_curve" and e.value == "inverse_power" for e in entries)


def test_selection_errors() -> None:
    tri, origins, ages = triangle("MT14-tail-curves-raa")
    options = {"origins": origins, "ages": ages, "scope": "S"}
    both = _selected("exponential_decay", tail=Assumption(
        method="MT02", name="tail_factor", value=1.02, who="owner", why="x"))  # fmt: skip
    with pytest.raises(AssumptionError, match="both set a tail"):
        chain_ladder_with_tail(tri, register=both, **options)
    with pytest.raises(AssumptionError, match="allowed"):
        chain_ladder_with_tail(tri, register=_selected("cubic"), **options)
