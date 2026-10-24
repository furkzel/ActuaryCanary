"""Interest-rate curves consistent with each scenario's inflation path.

For a curve in currency c, valued at the end of month t, the spot rate to tenor T (annual
compounding) is

    s(t, T) = g(t, T) + real_rate + term_premium * (1 - exp(-T / scale)) + shock(t) * exp(-T / 10)

where g is the geometric average annual inflation the scenario will produce over the T years
after t (its own price path for the reporting currency, the constant foreign inflation of the
exchange-rate series for a foreign one), and the shock is a slowly moving error (first-order
autoregression with its own random stream). The truth file carries the parts.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from actuarycanary.synthetic.days import month_end, month_start, year_of
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.feeds import date_series
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.scenario import Scenario


@dataclass(frozen=True)
class Rates:
    feed: pl.DataFrame
    truth: pl.DataFrame
    one_year: dict[str, np.ndarray]  # currency -> spot rate to one year, by month from base_month
    base_month: int


def _monthly_log_inflation(
    scenario: Scenario, market: Market, currency: str, months: np.ndarray
) -> np.ndarray:
    if currency == scenario.meta.reporting_currency:
        rates = scenario.market.cpi.annual_rate_by_year
        future = scenario.market.cpi.future_annual_rate
        if future is None:
            future = rates[max(rates)]
        years = year_of(month_start(months))
        annual = np.array([rates.get(int(y), future) for y in years])
    elif currency in market.foreign_inflation:
        annual = np.full(len(months), market.foreign_inflation[currency])
    else:
        raise ValueError(f"no inflation path for the currency {currency} of a yield curve")
    return np.log1p(annual) / 12.0


def build_rates(
    scenario: Scenario, market: Market, streams: Streams, first_month: int, last_month: int
) -> Rates:
    """Curves from the base month to `last_month`; the feed starts at `first_month`."""
    params = scenario.phase2.rates
    base_month = market.base_month
    n_future = max(params.tenors_months)
    horizon = np.arange(base_month, last_month + n_future + 2)
    months = np.arange(base_month, last_month + 1)
    rows: list[pl.DataFrame] = []
    one_year: dict[str, np.ndarray] = {}
    for curve in params.curves:
        log_inflation = _monthly_log_inflation(scenario, market, curve.currency, horizon)
        cumulative = np.concatenate([[0.0], np.cumsum(log_inflation)])  # to the end of month k
        rng = streams.get("phase2", "rates", curve.curve_id)
        innovation = rng.standard_normal(len(months))
        shock = np.zeros(len(months))
        scale = params.noise_sd * np.sqrt(1.0 - params.noise_persistence**2)
        for k in range(len(months)):
            previous = shock[k - 1] if k else 0.0
            shock[k] = params.noise_persistence * previous + scale * innovation[k]
        for tenor in params.tenors_months:
            # inflation of the months t+1 .. t+T, as an annual geometric average
            here = np.arange(len(months)) + 1
            average = np.expm1((cumulative[here + tenor] - cumulative[here]) * 12.0 / tenor)
            years = tenor / 12.0
            premium = params.term_premium * (1.0 - np.exp(-years / params.term_premium_scale_years))
            level = shock * np.exp(-years / 10.0)
            rate = average + params.real_rate + premium + level
            if tenor == 12:
                one_year[curve.currency] = rate
            keep = months >= first_month
            rows.append(
                pl.DataFrame(
                    {
                        "curve_id": [curve.curve_id] * int(keep.sum()),
                        "date": date_series("date", month_end(months[keep])),
                        "tenor_months": np.full(int(keep.sum()), tenor, dtype=np.int64),
                        "rate": np.round(rate[keep], 6),
                        "currency": [curve.currency] * int(keep.sum()),
                        "expected_inflation": np.round(average[keep], 6),
                        "real_rate": np.full(int(keep.sum()), params.real_rate),
                        "term_premium": np.round(np.full(int(keep.sum()), premium), 6),
                        "shock": np.round(level[keep], 6),
                    }
                )
            )
    both = pl.concat(rows).sort(["date", "curve_id", "tenor_months"])
    feed = both.select(
        [
            "curve_id",
            "date",
            "tenor_months",
            "rate",
            pl.lit("SPOT").alias("rate_type"),
            pl.lit("ANNUAL").alias("compounding"),
            "currency",
            pl.lit(params.source).alias("source"),
        ]
    )
    truth = both.select(
        [
            "curve_id",
            "date",
            "tenor_months",
            "rate",
            "expected_inflation",
            "real_rate",
            "term_premium",
            "shock",
        ]
    )
    return Rates(feed, truth, one_year, base_month)


def one_year_rate(rates: Rates, currency: str, month: np.ndarray) -> np.ndarray:
    """The one-year spot rate of a currency's first curve at the end of each month index."""
    series = rates.one_year[currency]
    return series[np.clip(month - rates.base_month, 0, len(series) - 1)]
