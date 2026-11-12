"""Price index and exchange rates for the treaty application (MT21, CV09, decision 0401).

The index of a date is the value of the series in that calendar month, or the latest value
before it; the generator publishes one value per month (`synthetic/market.py`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

PAYMENT_BY_PAYMENT = "payment_by_payment"
OCCURRENCE_DATE = "occurrence_date"
INDEX_CLAUSES = (PAYMENT_BY_PAYMENT, OCCURRENCE_DATE)

# currency_from, currency_to, day -> rate (amount in `to` per unit of `from`), None if unknown
FxLookup = Callable[[str, str, date], float | None]


def month_number(days: np.ndarray) -> np.ndarray:
    """Months since 1970-01 of datetime64[D] values."""
    return days.astype("datetime64[M]").astype(np.int64)


@dataclass(frozen=True)
class PriceIndex:
    series_id: str
    months: np.ndarray  # sorted month numbers
    values: np.ndarray

    def at(self, days: np.ndarray) -> np.ndarray:
        """Index value of each date: the value of its month or the latest month before it
        (the first value for dates before the series starts)."""
        position = np.searchsorted(self.months, month_number(days), side="right") - 1
        return self.values[np.clip(position, 0, len(self.values) - 1)]

    def at_date(self, day: date) -> float:
        return float(self.at(np.array([np.datetime64(day, "D")]))[0])


def price_indices(market: pl.DataFrame | None) -> dict[str, PriceIndex]:
    """The PRICE_INDEX series of the market feed, by series_id."""
    if market is None or market.height == 0:
        return {}
    frame = market
    if "kind" in frame.columns:
        frame = frame.filter(pl.col("kind") == "PRICE_INDEX")
    out: dict[str, PriceIndex] = {}
    for (series,), part in frame.drop_nulls(["date", "value"]).group_by(
        "series_id", maintain_order=True
    ):
        days = part["date"].cast(pl.Date).to_numpy().astype("datetime64[D]")
        months = month_number(days)
        order = np.argsort(months, kind="stable")
        months, values = months[order], part["value"].to_numpy()[order].astype(float)
        last = np.r_[months[1:] != months[:-1], True]  # last observation of a month wins
        out[str(series)] = PriceIndex(str(series), months[last], values[last])
    return out
