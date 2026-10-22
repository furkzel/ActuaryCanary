"""MT07 inflation-adjusted chain ladder: the constant-index property, the 50 per cent inflation
fixture built through the triangles of CV02, failure modes and the synthetic ground truth."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.bases import ValueBasis
from actuarycanary.methods.chain_ladder import Skipped, chain_ladder
from actuarycanary.methods.inflation_adjusted import (
    InflationAdjusted,
    future_cash_flows,
    inflation_adjusted_chain_ladder,
)
from actuarycanary.structures.periods import month_end, month_index
from actuarycanary.structures.triangles import TriangleSettings, build_triangles
from tests.convert.fixtures import market, valuations
from tests.methods.helpers import HAND, array, fitted
from tests.methods.medium import load_medium, medium, repair_amount_faults

CUT_OFF = date(2024, 12, 31)
SIZES = {2021: 100.0, 2022: 110.0, 2023: 120.0, 2024: 130.0}
SHARES = (0.5, 0.3, 0.15, 0.05)  # real development: share paid in each development year
YEARS = range(2021, 2025)


def _index(rate: float) -> list[tuple[str, str, date, float]]:
    """CPI_TR month ends 2021-01 to 2024-12 growing at `rate` a year (monthly compounding)."""
    first = month_index(date(2021, 1, 1))
    return [
        ("CPI_TR", "PRICE_INDEX", month_end(first + k), 100.0 * (1 + rate) ** (k / 12))
        for k in range(48)
    ]


def _fixture(rate: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(adjusted, nominal) paid triangles and nominal paid at the cut-off of four claims, one
    per origin, paying its real share at prices of each year end."""
    index = {d: v for _, _, d, v in _index(rate)}
    rows = []
    for origin in YEARS:
        paid = 0.0
        for k, year in enumerate(range(origin, 2025)):
            end = date(year, 12, 31)
            paid += SIZES[origin] * SHARES[k] * index[end] / index[CUT_OFF]
            rows.append((f"C{origin}", "TRY", end, paid, 0.0, 0.0, 0.0))
    claims = pl.DataFrame(
        {
            "claim_id": [f"C{o}" for o in YEARS],
            "occurrence_date": [date(o, 1, 15) for o in YEARS],
            "segment": ["NON_LIFE"] * 4,
            "line": ["MOTOR_TPL"] * 4,
        }
    )
    built = {
        basis: build_triangles(
            valuations(rows),
            claims,
            TriangleSettings(value_basis=basis),
            {"TRY": 1.0},
            "TRY",
            market=market(_index(rate)),
            price_index="CPI_TR",
            measures=("paid",),
        ).triangles[0]
        for basis in (ValueBasis.INFLATION_ADJUSTED, ValueBasis.NOMINAL)
    }
    adjusted, nominal = built[ValueBasis.INFLATION_ADJUSTED], built[ValueBasis.NOMINAL]
    return adjusted.cumulative, nominal.cumulative, nominal.latest


def _run(adjusted, nominal_paid, **options) -> InflationAdjusted:
    result = inflation_adjusted_chain_ladder(
        adjusted, nominal_paid=nominal_paid, cut_off=CUT_OFF, development_months=12, **options
    )
    assert isinstance(result, InflationAdjusted)
    return result


def test_fifty_per_cent_inflation_gives_back_the_real_pattern_and_the_nominal_unpaid() -> None:
    adjusted, nominal, paid = _fixture(0.5)
    real = np.cumsum(SHARES)
    np.testing.assert_allclose(adjusted[0], 100.0 * real, rtol=1e-9)
    result = _run(adjusted, paid, future_inflation=0.3, nominal=nominal)
    np.testing.assert_allclose(result.chain.factors, real[1:] / real[:-1], rtol=1e-9)
    np.testing.assert_allclose(
        result.ultimate_at_value_date_prices, list(SIZES.values()), rtol=1e-9
    )
    # future periods: middles 182.5, 547.5 and 912.5 days after the value date 2024-12-31
    t1, t2, t3 = 182.5 / 365.25, 547.5 / 365.25, 912.5 / 365.25
    expected = [
        0.0,
        110.0 * 0.05 * 1.3**t1,
        120.0 * (0.15 * 1.3**t1 + 0.05 * 1.3**t2),
        130.0 * (0.3 * 1.3**t1 + 0.15 * 1.3**t2 + 0.05 * 1.3**t3),
    ]
    assert result.nominal_unpaid is not None and result.nominal_ultimate is not None
    np.testing.assert_allclose(result.nominal_unpaid, expected, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(result.nominal_ultimate, paid + np.array(expected), rtol=1e-9)
    np.testing.assert_allclose(
        result.unpaid_at_value_date_prices,
        [0.0, 110 * 0.05, 120 * 0.2, 130 * 0.5],
        rtol=1e-9,
        atol=1e-12,
    )
    removed = result.inflation_removed
    assert removed is not None and (removed > 1).all()  # nominal factors carry the inflation


def test_constant_index_gives_nominal_chain_ladder() -> None:
    adjusted, nominal, paid = _fixture(0.0)
    result = _run(adjusted, paid)
    plain = fitted(nominal)
    np.testing.assert_allclose(result.chain.factors, plain.factors, rtol=1e-12)
    np.testing.assert_allclose(result.ultimate_at_value_date_prices, plain.ultimate, rtol=1e-12)


def test_without_future_inflation_only_value_date_prices_are_given() -> None:
    result = _run(array(HAND["paid"]), np.zeros(4))
    assert result.future_inflation is None
    assert result.nominal_unpaid is None and result.nominal_ultimate is None
    flows = future_cash_flows(result, CUT_OFF, 12)
    assert [f.end for f in flows] == [date(2025, 12, 31), date(2026, 12, 31), date(2027, 12, 31)]
    assert all(f.nominal is None for f in flows)
    assert sum(f.at_value_date_prices for f in flows) == pytest.approx(
        result.unpaid_at_value_date_prices.sum()
    )
    assert flows[0].payment_date == date(2025, 7, 1)


def test_tail_payment_falls_in_the_period_after_the_last_age() -> None:
    result = _run(array(HAND["paid"]), np.zeros(4), tail_factor=1.1)
    plain = chain_ladder(array(HAND["paid"]), tail_factor=1.1)
    assert not isinstance(plain, Skipped)
    np.testing.assert_allclose(result.unpaid_at_value_date_prices, plain.reserve, rtol=1e-12)
    assert result.future.shape[1] == 4


def test_chain_ladder_failure_is_passed_on() -> None:
    result = inflation_adjusted_chain_ladder(
        np.array([[1.0, 2.0], [1.0, np.nan]]),
        nominal_paid=np.zeros(2),
        cut_off=CUT_OFF,
        development_months=12,
    )
    assert result == Skipped("MT07", "chain ladder needs at least 3 origin periods")


# Ground truth (record 0044): value-date ultimates of accident years with at least three years
# of development against the true ultimate with every payment restated to the cut-off prices
# (truth column ultimate_try_at_cutoff_prices), after undoing the injected amount faults.
TOLERANCE = 0.05
# Measured 2026-10-22 (record 0063): MOTOR_TPL 2023, 36 months old, is -15.0 % in both scenarios.
# Over 61 simulations its ratio has mean 0.96 and standard deviation 0.107, so the miss is
# process variance of a young long-tailed origin, not a fault of the method. High_inflation TPL
# 2016 (-5.1 % in record 0044) is -2.9 % on the data of the current generator and is checked.
KNOWN_EXCEPTIONS = {
    ("baseline", "MOTOR_TPL", "2023"),
    ("high_inflation", "MOTOR_TPL", "2023"),
}


def _ground_truth(scenario: str) -> dict[tuple[str, str, str], float]:
    data = load_medium(scenario)
    rows = repair_amount_faults(data.valuations, data.faults)
    triangles = build_triangles(
        rows,
        data.claims,
        TriangleSettings(value_basis=ValueBasis.INFLATION_ADJUSTED),
        data.rates,
        "TRY",
        market=data.market,
        price_index="CPI_TR",
        measures=("paid",),
    )
    truth = (
        pl.read_csv(data.truth / "ultimates.csv")
        .group_by("line", "accident_year")
        .agg(pl.col("ultimate_try_at_cutoff_prices").sum())
    )
    true = {(r[0], str(r[1])): r[2] for r in truth.iter_rows()}
    ratios: dict[tuple[str, str, str], float] = {}
    for triangle in triangles.triangles:
        result = inflation_adjusted_chain_ladder(
            triangle.cumulative,
            nominal_paid=np.zeros(len(triangle.origins)),
            cut_off=triangles.cut_off,
            development_months=12,
            calendar=triangle.calendar,
        )
        assert isinstance(result, InflationAdjusted)
        line = triangle.group[1]
        for i, origin in enumerate(triangle.origins):
            if triangle.latest_index[i] >= 2:
                ratios[(scenario, line, origin)] = (
                    result.ultimate_at_value_date_prices[i] / true[(line, origin)]
                )
    return ratios


@pytest.fixture(scope="module", params=["baseline", "high_inflation"])
def ground_truth(request: pytest.FixtureRequest) -> dict[tuple[str, str, str], float]:
    if not medium(request.param).is_dir():
        pytest.skip(f"run `just synth {request.param} medium` first")
    return _ground_truth(request.param)


@pytest.mark.slow
@pytest.mark.integration
def test_ground_truth_value_date_ultimates_within_five_per_cent(ground_truth) -> None:
    checked = {k: r for k, r in ground_truth.items() if k not in KNOWN_EXCEPTIONS}
    assert len(checked) >= 22
    outside = {k: round(r, 4) for k, r in checked.items() if abs(r - 1) > TOLERANCE}
    assert not outside


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.xfail(
    strict=True, reason="MOTOR_TPL 2023 at 36 months outside 5 per cent (records 0044, 0063)"
)
def test_ground_truth_known_exceptions(ground_truth) -> None:
    exceptions = {k: r for k, r in ground_truth.items() if k in KNOWN_EXCEPTIONS}
    assert exceptions
    assert all(abs(r - 1) <= TOLERANCE for r in exceptions.values()), exceptions
