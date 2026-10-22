"""Restatement to the prices of one value date with a monthly price index (CV02).

The index value of a date is the value of the calendar month containing it. A missing month
takes the latest earlier month and is flagged; with no earlier month the amount cannot be
restated: its factor is null and it is excluded from inflation-adjusted views.
"""

from datetime import date

import polars as pl

from actuarycanary.convert.market import ConversionError, MarketData
from actuarycanary.structures.periods import month_index

FLAG_EARLIER_MONTH = "index of an earlier month"


def restatement_factors(
    market: MarketData, series_id: str, value_date: date, months: pl.Series
) -> pl.DataFrame:
    """Factor I(value date) / I(month) for each distinct month index in `months`.

    Returns month, factor (null: no index for the month or any earlier one) and flag.
    """
    table = market.index(series_id)
    if table is None:
        raise ConversionError(f"market data has no PRICE_INDEX series {series_id}")
    value_month = month_index(value_date)
    at_value = table.filter(pl.col("key") <= value_month).sort("key")
    if at_value.height == 0:
        raise ConversionError(
            f"price index {series_id} has no value on or before the value date {value_date}"
        )
    base = float(at_value["value"][-1])
    requested = pl.DataFrame({"month": months.unique().sort()})
    found = requested.join_asof(
        table.with_columns(pl.col("key").alias("found")),
        left_on="month",
        right_on="key",
        strategy="backward",
    )
    return found.select(
        "month",
        (base / pl.col("value")).alias("factor"),
        pl.when(pl.col("found").is_not_null() & (pl.col("found") != pl.col("month")))
        .then(pl.lit(FLAG_EARLIER_MONTH))
        .otherwise(pl.lit(""))
        .alias("flag"),
    )
