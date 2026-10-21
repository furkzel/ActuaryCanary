"""MT01 on every basis: gross, ceded and net (CV03), nominal and inflation-adjusted (CV02),
constant development rates (CV01), counts, recoveries and the underwriting origin axis.

The hand fixture is `tests.convert.fixtures`: claims A (TRY), B (USD) and C (EUR) over the
month ends 2024-01 to 2024-03, index 100, 110 and 132 for the three months. Origins are the
first-valuation months (no claims table): January for A and B, February for C, March empty.
"""

from datetime import date
from typing import Any

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.rates import development_rates
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import (
    OriginAxis,
    TriangleError,
    TriangleSet,
    TriangleSettings,
    build_triangles,
)
from tests.convert.fixtures import MAR, MARKET_ROWS, VALUATION_ROWS, market, valuations

MONTHLY: dict[str, Any] = {"origin_period": Period.MONTH, "development_period": Period.MONTH}
GROUP = ("UNKNOWN", "UNKNOWN")
NAN = np.nan
RATES = {"TRY": 1.0, "USD": 34.0, "EUR": 100.0}  # period-end rates of 2024-03


def _build(
    reinsurance: str = "GROSS",
    value: str = "NOMINAL",
    frame: pl.DataFrame | None = None,
    measures: tuple[str, ...] = ("paid", "incurred"),
    **extra,
) -> TriangleSet:
    settings = TriangleSettings(
        reinsurance_basis=ReinsuranceBasis(reinsurance),
        value_basis=ValueBasis(value),
        **MONTHLY,
        **extra,
    )
    return build_triangles(
        valuations() if frame is None else frame,
        None,
        settings,
        RATES,
        "TRY",
        market=market(),
        price_index="CPI_TR",
        measures=measures,
    )


def _cells(result: TriangleSet, measure: str) -> np.ndarray:
    return result.get(measure, GROUP).cumulative


def _assert_cells(actual: np.ndarray, expected: list[list[float]]) -> None:
    np.testing.assert_allclose(actual, np.array(expected), rtol=0, atol=1e-9, equal_nan=True)


def test_nominal_gross_converts_every_amount_with_the_constant_development_rate() -> None:
    result = _build()
    assert result.get("paid", GROUP).latest.tolist() == [1320.0, 400.0, 0.0]
    assert result.get("incurred", GROUP).latest.tolist() == [1320.0, 600.0, 0.0]
    assert result.not_converted.height == 0


def test_cv03_net_ceded_and_gross_on_the_nominal_basis() -> None:
    ceded = _build("CEDED", measures=("paid", "case_reserve", "incurred"))
    net = _build("NET", measures=("paid", "case_reserve", "incurred"))
    assert ceded.get("paid", GROUP).latest.tolist() == [120.0, 200.0, 0.0]
    assert net.get("paid", GROUP).latest.tolist() == [1200.0, 200.0, 0.0]
    assert net.get("case_reserve", GROUP).latest.tolist() == [0.0, 100.0, 0.0]
    assert net.get("incurred", GROUP).latest.tolist() == [1200.0, 300.0, 0.0]


def test_cv02_inflation_adjusted_gross_by_hand() -> None:
    """Flows are converted at the average rate of their month and restated from it; the case
    reserve at the period-end rate and the index of its valuation month."""
    result = _build(value="INFLATION_ADJUSTED")
    _assert_cells(
        _cells(result, "paid"),
        [[528.0, 528.0, 1388.0], [0.0, 320.0, NAN], [0.0, NAN, NAN]],
    )
    _assert_cells(
        _cells(result, "incurred"),
        [[798.6, 756.6, 1388.0], [600.0, 520.0, NAN], [0.0, NAN, NAN]],
    )
    assert result.value_date == MAR and result.price_index == "CPI_TR"
    assert result.not_converted.height == 0


def test_cv02_inflation_adjusted_net_by_hand() -> None:
    result = _build("NET", "INFLATION_ADJUSTED")
    _assert_cells(
        _cells(result, "paid"),
        [[475.2, 475.2, 1255.2], [0.0, 160.0, NAN], [0.0, NAN, NAN]],
    )
    _assert_cells(
        _cells(result, "incurred"),
        [[719.4, 694.2, 1255.2], [300.0, 260.0, NAN], [0.0, NAN, NAN]],
    )


@pytest.mark.parametrize("value", ["NOMINAL", "INFLATION_ADJUSTED"])
def test_cv03_net_equals_gross_minus_ceded_in_every_cell(value: str) -> None:
    measures = ("paid", "case_reserve", "incurred")
    gross, ceded, net = (_build(b, value, measures=measures) for b in ("GROSS", "CEDED", "NET"))
    for measure in measures:
        np.testing.assert_allclose(
            _cells(net, measure),
            _cells(gross, measure) - _cells(ceded, measure),
            equal_nan=True,
            atol=1e-9,
        )


def test_cv03_a_missing_ceded_field_makes_ceded_and_net_unavailable_not_equal_to_gross() -> None:
    frame = valuations().drop("ceded_paid_to_date", "ceded_reserve")
    for basis in ("CEDED", "NET"):
        with pytest.raises(TriangleError, match="ceded_paid_to_date.*CV03"):
            _build(basis, frame=frame)
    assert _build("GROSS", frame=frame).get("paid", GROUP).latest[0] == 1320.0


def test_cv03_an_empty_cell_of_a_present_ceded_field_counts_as_zero() -> None:
    rows = [(*r[:5], None, None) if r[0] == "A" else r for r in VALUATION_ROWS]
    frame = valuations(rows).with_columns(
        pl.col("ceded_paid_to_date").cast(pl.Float64), pl.col("ceded_reserve").cast(pl.Float64)
    )
    net = _build("NET", frame=frame)
    assert net.get("paid", GROUP).latest.tolist() == [1320.0, 200.0, 0.0]  # A has no cession


def test_recoveries_are_gross_only_and_shown_as_their_own_measures() -> None:
    frame = valuations().with_columns(
        pl.Series("subrogation_to_date", [5.0, 5.0, 10.0, 0.0, 1.0, 0.0, 0.0]),
        pl.Series("salvage_to_date", [0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0]),
    )
    result = _build(
        frame=frame, measures=("subrogation", "salvage", "recoveries", "paid_net_of_recoveries")
    )
    assert result.get("subrogation", GROUP).latest.tolist() == [10.0 + 34.0, 0.0, 0.0]
    assert result.get("salvage", GROUP).latest.tolist() == [2.0, 0.0, 0.0]
    assert result.get("recoveries", GROUP).latest.tolist() == [46.0, 0.0, 0.0]
    # CV03: paid net of recoveries is paid - subrogation - salvage
    assert result.get("paid_net_of_recoveries", GROUP).latest.tolist() == [
        1320.0 - 46.0,
        400.0,
        0.0,
    ]
    with pytest.raises(TriangleError, match="only GROSS exists"):
        _build("NET", frame=frame, measures=("recoveries",))
    with pytest.raises(TriangleError, match="only GROSS exists"):
        _build("CEDED", frame=frame, measures=("paid_net_of_recoveries",))


def test_cl04_counts_reported_open_and_closed() -> None:
    """CL04: reported counts rows on or before the point; open and closed use the as-of status."""
    status = ["OPEN", "OPEN", "CLOSED", "OPEN", "CLOSED_NIL", "OPEN", "REOPENED"]
    frame = valuations().with_columns(pl.Series("status", status))
    result = _build(frame=frame, measures=("reported_count", "open_count", "closed_count"))
    _assert_cells(_cells(result, "reported_count"), [[2, 2, 2], [1, 1, NAN], [0, NAN, NAN]])
    _assert_cells(_cells(result, "closed_count"), [[0, 0, 2], [0, 0, NAN], [0, NAN, NAN]])
    _assert_cells(_cells(result, "open_count"), [[2, 2, 0], [1, 1, NAN], [0, NAN, NAN]])


def test_cumulative_of_the_incremental_triangle_is_the_cumulative_triangle() -> None:
    result = _build(
        "NET", "INFLATION_ADJUSTED", measures=("paid", "incurred", "case_reserve", "closed_count")
    )
    for triangle in result.triangles:
        incremental = np.where(triangle.observed, triangle.incremental, 0.0)
        np.testing.assert_allclose(
            np.cumsum(incremental, axis=1)[triangle.observed],
            triangle.cumulative[triangle.observed],
            atol=1e-9,
        )


@pytest.mark.parametrize("basis", [("GROSS", "NOMINAL"), ("NET", "INFLATION_ADJUSTED")])
def test_results_do_not_depend_on_row_order(basis: tuple[str, str]) -> None:
    frame = valuations()
    shuffled = frame.sample(fraction=1.0, shuffle=True, seed=7)
    one, two = _build(*basis, frame=frame), _build(*basis, frame=shuffled)
    for a, b in zip(one.triangles, two.triangles, strict=True):
        np.testing.assert_allclose(a.cumulative, b.cumulative, equal_nan=True, atol=1e-9)


def test_amounts_without_a_rate_or_index_leave_the_adjusted_triangles_and_are_listed() -> None:
    rows = [*VALUATION_ROWS, ("D", "GBP", MAR, 7.0, 3.0, 0.0, 0.0)]
    result = _build(value="INFLATION_ADJUSTED", frame=valuations(rows))
    assert result.get("paid", GROUP).latest.tolist() == [1388.0, 320.0, 0.0]
    assert result.not_converted.to_dicts() == [
        {"currency": "GBP", "claims": 1, "paid": 7.0, "incurred": 10.0}
    ]
    assert {f.rule for f in result.findings} == {"CV01"}


def test_cv02_a_flow_that_cannot_be_converted_keeps_the_claim_out_from_that_row_on() -> None:
    """Without a USD average rate for January the first flow of B is lost, so every later
    cumulative amount of B would be wrong: the claim is left out from that row on."""
    rows = [r for r in MARKET_ROWS if not (r[0] == "USD/TRY" and r[2] == date(2024, 1, 31))]
    result = build_triangles(
        valuations(),
        None,
        TriangleSettings(value_basis=ValueBasis.INFLATION_ADJUSTED, **MONTHLY),
        RATES,
        "TRY",
        market=market(rows),
        price_index="CPI_TR",
    )
    assert result.get("paid", GROUP).latest.tolist() == [332.0, 320.0, 0.0]
    assert result.not_converted["currency"].to_list() == ["USD"]


def test_cv02_the_value_date_chooses_the_prices() -> None:
    february = _build(value="INFLATION_ADJUSTED", value_date=date(2024, 2, 29))
    march = _build(value="INFLATION_ADJUSTED")
    # one January flow of A (100) at TRY: restated by 110/100 instead of 132/100
    assert february.get("paid", GROUP).cumulative[0, 0] == pytest.approx(528.0 / 1.2)
    assert march.get("paid", GROUP).cumulative[0, 0] == pytest.approx(528.0)


def test_cv02_the_adjusted_basis_needs_market_data() -> None:
    with pytest.raises(TriangleError, match="market data"):
        build_triangles(
            valuations(),
            None,
            TriangleSettings(value_basis=ValueBasis.INFLATION_ADJUSTED, **MONTHLY),
            RATES,
            "TRY",
        )


def test_the_constant_development_rate_of_a_market_comes_from_its_stock_rate() -> None:
    rates = development_rates("TRY", ["TRY", "USD", "EUR"], market(), MAR)
    result = build_triangles(
        valuations(), None, TriangleSettings(**MONTHLY), rates, "TRY", measures=("paid",)
    )
    assert result.get("paid", GROUP).latest.tolist() == [1320.0, 400.0, 0.0]


def _origin_fixture() -> tuple[pl.DataFrame, pl.DataFrame]:
    claims = pl.DataFrame(
        {
            "claim_id": ["A", "B", "C"],
            "occurrence_date": [date(2024, 1, 5)] * 3,
            "report_date": [date(2024, 1, 20), date(2024, 1, 25), date(2024, 2, 20)],
            "policy_id": ["P1", "P2", "P2"],
            "segment": ["NON_LIFE"] * 3,
            "line": ["MOTOR_OD"] * 3,
            SOURCE_ROW: [2, 3, 4],
        }
    )
    policies = pl.DataFrame(
        {
            "policy_id": ["P1", "P2"],
            "start_date": [date(2023, 11, 15), date(2024, 1, 10)],
            SOURCE_ROW: [2, 3],
        }
    )
    return claims, policies


def test_cv04_origin_by_occurrence_report_or_underwriting_date() -> None:
    claims, policies = _origin_fixture()

    def latest(axis: OriginAxis) -> dict[str, float]:
        result = build_triangles(
            valuations(),
            claims,
            TriangleSettings(
                origin_axis=axis, origin_period=Period.YEAR, development_period=Period.MONTH
            ),
            RATES,
            "TRY",
            policies=policies,
            measures=("paid",),
        )
        triangle = result.get("paid", ("NON_LIFE", "MOTOR_OD"))
        return dict(zip(triangle.origins, triangle.latest.tolist(), strict=True))

    assert latest(OriginAxis.ACCIDENT) == {"2024": 1720.0}
    assert latest(OriginAxis.UNDERWRITING) == {"2023": 300.0, "2024": 1420.0}
    assert latest(OriginAxis.REPORT) == {"2024": 1720.0}


def test_cv04_the_underwriting_axis_needs_claims_with_policies() -> None:
    claims, _ = _origin_fixture()
    settings = TriangleSettings(origin_axis=OriginAxis.UNDERWRITING, **MONTHLY)
    for given in ((None, None), (claims, None)):
        with pytest.raises(TriangleError, match="underwriting origin axis needs"):
            build_triangles(valuations(), given[0], settings, RATES, "TRY", policies=given[1])


def test_cv04_a_claim_whose_policy_has_no_start_date_is_left_out_and_listed() -> None:
    claims, policies = _origin_fixture()
    policies = policies.with_columns(
        pl.when(pl.col("policy_id") == "P1")
        .then(None)
        .otherwise(pl.col("start_date"))
        .alias("start_date")
    )
    result = build_triangles(
        valuations(),
        claims,
        TriangleSettings(origin_axis=OriginAxis.UNDERWRITING, **MONTHLY),
        RATES,
        "TRY",
        policies=policies,
        measures=("paid",),
    )
    assert [f.rule for f in result.findings] == ["MT01"]
    assert result.claims_used == 2


def test_unknown_measures_are_rejected() -> None:
    with pytest.raises(TriangleError, match="unknown measures: nonsense"):
        _build(measures=("nonsense",))


def test_cv02_a_value_date_month_without_an_index_value_is_noted() -> None:
    rows = [r for r in MARKET_ROWS if not (r[1] == "PRICE_INDEX" and r[2] == MAR)]
    result = build_triangles(
        valuations(),
        None,
        TriangleSettings(value_basis=ValueBasis.INFLATION_ADJUSTED, **MONTHLY),
        RATES,
        "TRY",
        market=market(rows),
        price_index="CPI_TR",
    )
    messages = [f.message for f in result.findings if f.rule == "CV02" and f.severity == "INFO"]
    assert any("month of the value date 2024-03-31" in m for m in messages)
