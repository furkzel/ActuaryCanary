"""Constant development rates for triangles and the methods built on them (CV01)."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from actuarycanary.convert.currency import MAX_LOOKBACK_DAYS, Rule, lookup_rates
from actuarycanary.convert.market import MarketData


@dataclass(frozen=True)
class DevelopmentRates:
    """One rate per original currency; `flags` names the fallback used for a currency."""

    rates: dict[str, float]
    rate_date: date | None
    flags: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()


def development_rates(
    reporting_currency: str,
    currencies: Iterable[str] = (),
    market: MarketData | None = None,
    rate_date: date | None = None,
    max_lookback_days: int = MAX_LOOKBACK_DAYS,
) -> DevelopmentRates:
    """Rate per original currency into the reporting currency at the development rate date.

    It is the stock rate of that date (CV01): the FX_PERIOD_END rate of its month, else the
    FX_SPOT rate of the date or the nearest earlier one within `max_lookback_days`, flagged.
    Without market data only amounts already in the reporting currency have a rate (1); every
    other currency is listed in `missing` and stays unconverted (CV01).
    """
    wanted = sorted({c for c in currencies if c and c != reporting_currency})
    if market is None or rate_date is None or not wanted:
        return DevelopmentRates({reporting_currency: 1.0}, rate_date, {}, tuple(wanted))
    keys = pl.DataFrame({"currency": wanted, "day": [rate_date] * len(wanted)})
    found = lookup_rates(market, reporting_currency, keys, Rule.STOCK, max_lookback_days)
    rates = {reporting_currency: 1.0}
    flags: dict[str, str] = {}
    for currency, rate, flag in found.select("currency", "rate", "flag").iter_rows():
        if rate is not None:
            rates[currency] = rate
            if flag:
                flags[currency] = flag
    missing = tuple(c for c in wanted if c not in rates)
    return DevelopmentRates(rates, rate_date, flags, missing)
