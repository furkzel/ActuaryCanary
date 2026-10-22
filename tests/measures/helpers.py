"""Tiny feeds and a call into the engine, for the measure tests (frames built in code)."""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import MarketData
from actuarycanary.convert.rates import DevelopmentRates, development_rates
from actuarycanary.measures.engine import run_measure
from actuarycanary.measures.model import (
    Basis,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    MeasureResult,
    with_refs,
)
from actuarycanary.measures.output import dimensions
from actuarycanary.measures.port import MethodsPort
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.periods import Period
from tests.convert.fixtures import market_frame
from tests.quality.builders import frames

CATALOGUE = load_specs()


def make_inputs(
    rows: dict[str, list[dict[str, Any]]],
    cut_off: date | None = None,
    market_rows: list[tuple[str, str, date, float]] | None = None,
    methods: MethodsPort | None = None,
    **extra: Any,
) -> MeasureInputs:
    """Inputs from rows by concept (`tests.quality.builders` frames); TRY is the reporting
    currency and the only one with a rate unless `market_rows` give others."""
    built = frames(rows)
    if cut_off is None:
        latest = built["claim_valuations"]["valuation_date"].max()
        assert isinstance(latest, date)
        cut_off = latest
    market = MarketData.from_frame(market_frame(market_rows)) if market_rows else None
    currencies = (
        built["claim_valuations"]["currency"].drop_nulls().unique().to_list()
        if "claim_valuations" in built
        else []
    )
    rates = (
        development_rates("TRY", currencies, market, cut_off)
        if market is not None
        else DevelopmentRates({"TRY": 1.0}, cut_off)
    )
    arguments: dict[str, Any] = {"price_index": "CPI_TR", **extra}
    if methods is not None:
        arguments["methods"] = methods
    return MeasureInputs(with_refs(built), cut_off, "TRY", rates, market, **arguments)


def measure(
    inputs: MeasureInputs,
    measure_id: str,
    *breakdowns: str,
    period: Period = Period.YEAR,
    reinsurance: ReinsuranceBasis = ReinsuranceBasis.GROSS,
    currency: CurrencyView = CurrencyView.REPORTING,
    value: ValueBasis = ValueBasis.NOMINAL,
    **request: Any,
) -> MeasureResult:
    basis = Basis(reinsurance, currency, value)
    return run_measure(
        CATALOGUE, inputs, measure_id, MeasureRequest(breakdowns, period, basis, **request)
    )


def table(result: MeasureResult, column: str = "value") -> dict[tuple, Any]:
    """The values of a result by the tuple of its breakdown columns."""
    assert result.frame is not None, result.reason
    keys = dimensions(result)
    return {tuple(row[k] for k in keys): row[column] for row in result.frame.iter_rows(named=True)}


def values(result: MeasureResult, column: str = "value") -> list[Any]:
    assert result.frame is not None, result.reason
    return result.frame[column].to_list()


def one(result: MeasureResult, column: str = "value") -> Any:
    assert result.frame is not None, result.reason
    assert result.frame.height == 1, result.frame
    return result.frame[column][0]


__all__ = ["CATALOGUE", "make_inputs", "measure", "one", "pl", "table", "values"]
