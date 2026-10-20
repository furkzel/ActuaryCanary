"""Market world: a consumer price index with a chosen inflation path and exchange rates as
random walks. The world continues past the data cut-off, because payments made after it
belong to the truth."""

from dataclasses import dataclass

import numpy as np

from actuarycanary.synthetic.days import (
    DAYS_PER_YEAR,
    month_end,
    month_index,
    month_start,
    to_day,
    year_of,
)
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.scenario import Scenario

FUTURE_YEARS = 14  # simulated past the cut-off: longest settlement plus reopening


@dataclass(frozen=True)
class Market:
    base_day: int
    base_month: int
    cut_off_day: int
    cpi_base_value: float
    cpi: np.ndarray  # one value per month, starting at the base month
    cpi_monthly_rate: np.ndarray  # growth of each month over the one before (first is 0)
    fx: dict[str, np.ndarray]  # currency -> daily QUOTE-per-BASE rate, starting at the base day
    fx_start: dict[str, float]
    foreign_inflation: dict[str, float]

    def month_position(self, days: np.ndarray) -> np.ndarray:
        return np.clip(month_index(days) - self.base_month, 0, len(self.cpi) - 1)

    def cpi_at(self, days: np.ndarray) -> np.ndarray:
        return self.cpi[self.month_position(days)]

    def price_factor(self, days: np.ndarray) -> np.ndarray:
        """CPI at `days` relative to the base date (1.0 at the base date)."""
        return self.cpi_at(days) / self.cpi_base_value

    def fx_at(self, currency: str, days: np.ndarray) -> np.ndarray:
        rates = self.fx[currency]
        return rates[np.clip(np.asarray(days) - self.base_day, 0, len(rates) - 1)]

    @property
    def last_day(self) -> int:
        return self.base_day + len(next(iter(self.fx.values()), np.zeros(1))) - 1


def _annual_rate_lookup(scenario: Scenario) -> tuple[dict[int, float], float]:
    rates = scenario.market.cpi.annual_rate_by_year
    future = scenario.market.cpi.future_annual_rate
    if future is None:
        future = rates[max(rates)]
    return rates, future


def build_market(scenario: Scenario, streams: Streams) -> Market:
    rates, future = _annual_rate_lookup(scenario)
    base_day = to_day(scenario.meta.base_date)
    cut_off_day = to_day(scenario.meta.valuation.last)
    base_month = int(month_index(base_day))
    n_months = int(month_index(cut_off_day)) - base_month + 1 + FUTURE_YEARS * 12

    months = base_month + np.arange(n_months)
    month_years = year_of(month_start(months))
    annual = np.array([rates.get(int(y), future) for y in month_years])
    smooth = (1.0 + annual) ** (1.0 / 12.0) - 1.0
    noise = (
        streams.get("market", "cpi").standard_normal(n_months)
        * scenario.market.cpi.monthly_noise_sd
    )
    rate = np.maximum(smooth + noise, -0.5)
    rate[0] = 0.0
    cpi = np.round(scenario.market.cpi.base_value * np.cumprod(1.0 + rate), 4)  # as published
    rate = np.concatenate([[0.0], cpi[1:] / cpi[:-1] - 1.0])

    n_days = int(month_end(base_month + n_months - 1)) - base_day + 1
    days = base_day + np.arange(n_days)
    day_years = year_of(days)
    try_annual = np.array(
        [rates.get(int(y), future) for y in range(day_years[0], day_years[-1] + 1)]
    )
    try_by_day = try_annual[day_years - day_years[0]]
    fx: dict[str, np.ndarray] = {}
    fx_start: dict[str, float] = {}
    foreign: dict[str, float] = {}
    for pair in scenario.market.fx:
        base_ccy, quote_ccy = pair.series_id.split("/")
        if quote_ccy != scenario.meta.reporting_currency:
            raise ValueError(f"{pair.series_id}: the quote currency must be the reporting currency")
        drift = (np.log1p(try_by_day) - np.log1p(pair.foreign_inflation)) / DAYS_PER_YEAR
        sd = pair.monthly_vol / np.sqrt(30.4375)
        steps = drift + sd * streams.get("market", "fx", pair.series_id).standard_normal(n_days)
        steps[0] = 0.0
        fx[base_ccy] = np.round(pair.start * np.exp(np.cumsum(steps)), 6)
        fx_start[base_ccy] = pair.start
        foreign[base_ccy] = pair.foreign_inflation
    return Market(
        base_day,
        base_month,
        cut_off_day,
        scenario.market.cpi.base_value,
        cpi,
        rate,
        fx,
        fx_start,
        foreign,
    )
