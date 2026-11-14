"""Measure inputs of a generated scenario, built in memory from the simulation (nothing written,
nothing read back): the canonical feeds of the generator as the measures read them."""

from datetime import date

import polars as pl

from actuarycanary.convert.market import MarketData
from actuarycanary.convert.rates import development_rates
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.measures.model import MeasureInputs, with_refs
from actuarycanary.synthetic.build import Simulation


def inputs_of(sim: Simulation) -> MeasureInputs:
    feeds: dict[str, pl.DataFrame] = {}
    for feed, sheets in sim.frames.items():
        frame = pl.concat(sheets.values())
        feeds[feed] = frame.with_row_index(SOURCE_ROW, offset=2).cast({SOURCE_ROW: pl.Int64})
    cut_off = feeds["claim_valuations"]["valuation_date"].max()
    assert isinstance(cut_off, date)
    market = MarketData.from_frame(feeds["market"])
    currencies = feeds["claim_valuations"]["currency"].drop_nulls().unique().to_list()
    rates = development_rates(sim.scenario.meta.reporting_currency, currencies, market, cut_off)
    return MeasureInputs(
        with_refs(feeds), cut_off, sim.scenario.meta.reporting_currency, rates, market, "CPI_TR"
    )
