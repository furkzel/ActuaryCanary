"""Currency conversion by the rules of CV01.

Each amount is converted with the rate type that matches its nature: flows at the FX_SPOT
rate of their booking date, flows derived from two claim valuations at the FX_PERIOD_AVERAGE
rate of their booking month, stocks at the FX_PERIOD_END rate of the valuation month, and
development analysis at one constant rate. A rate that had to be replaced by a fallback is
flagged; an amount without any rate is not converted and is reported apart.
"""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

import polars as pl

from actuarycanary.convert.market import (
    FX_PERIOD_AVERAGE,
    FX_PERIOD_END,
    FX_SPOT,
    MarketData,
    month_of,
)

MAX_LOOKBACK_DAYS = 7  # CV01 max_lookback_days

FLAG_EARLIER_SPOT = "earlier FX_SPOT rate"
FLAG_AVERAGE = "FX_PERIOD_AVERAGE instead of FX_SPOT"
FLAG_SPOT_FOR_END = "FX_SPOT instead of FX_PERIOD_END"


class Rule(StrEnum):
    FLOW = "flow"  # booked on a date: FX_SPOT of the date
    DERIVED_FLOW = "derived_flow"  # booked in a month (difference of valuations): average
    STOCK = "stock"  # valued at a date: FX_PERIOD_END of the month


def _fill(
    open_rows: pl.DataFrame, table: pl.DataFrame | None, by: str, flag: str, days: int
) -> pl.DataFrame:
    """Rates for rows without one yet from `table`; `by` is "month" or "asof"."""
    if table is None or open_rows.height == 0:
        return open_rows
    rows = open_rows.drop("rate", "flag")
    if by == "month":
        found = rows.with_columns(month_of("day").alias("key")).join(table, on="key", how="left")
        return found.select("currency", "day", "rate", pl.lit(flag).alias("flag"))
    right = table.with_columns(pl.col("key").alias("found"))
    found = rows.sort("day").join_asof(
        right,
        left_on="day",
        right_on="key",
        strategy="backward",
        tolerance=timedelta(days=days),
    )
    label = pl.when(pl.col("found") == pl.col("day")).then(pl.lit("")).otherwise(pl.lit(flag))
    return found.select("currency", "day", "rate", label.alias("flag"))


def lookup_rates(
    market: MarketData | None,
    target: str,
    keys: pl.DataFrame,
    rule: Rule,
    max_lookback_days: int = MAX_LOOKBACK_DAYS,
) -> pl.DataFrame:
    """Rate into `target` for each distinct (currency, day) of `keys`.

    Returns currency, day, rate (null: no applicable rate) and flag ("" when the rate is the
    one the rule names). An amount whose currency is the target uses the rate 1.
    """
    schema = {"currency": pl.String, "day": pl.Date, "rate": pl.Float64, "flag": pl.String}
    parts: list[pl.DataFrame] = []
    for (currency,), part in keys.select("currency", "day").unique().group_by("currency"):
        rows = part.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("rate"), pl.lit("").alias("flag")
        )
        if currency == target:
            parts.append(rows.with_columns(pl.lit(1.0).alias("rate")))
            continue
        if market is None:
            parts.append(rows)
            continue
        spot = market.pair(FX_SPOT, str(currency), target)
        average = market.pair(FX_PERIOD_AVERAGE, str(currency), target)
        end = market.pair(FX_PERIOD_END, str(currency), target)
        steps: list[tuple[pl.DataFrame | None, str, str]] = {
            Rule.FLOW: [(spot, "asof", FLAG_EARLIER_SPOT), (average, "month", FLAG_AVERAGE)],
            Rule.DERIVED_FLOW: [(average, "month", "")],
            Rule.STOCK: [(end, "month", ""), (spot, "asof", FLAG_SPOT_FOR_END)],
        }[rule]
        for table, by, flag in steps:
            open_rows = rows.filter(pl.col("rate").is_null())
            known = _fill(open_rows, table, by, flag, max_lookback_days)
            known = known.filter(pl.col("rate").is_not_null())
            if known.height:
                still = open_rows.join(
                    known.select("currency", "day"), on=["currency", "day"], how="anti"
                )
                rows = pl.concat([rows.filter(pl.col("rate").is_not_null()), known, still])
        parts.append(rows)
    if not parts:
        return pl.DataFrame(schema=schema)
    return pl.concat(parts).select(schema.keys()).cast(schema)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Conversion:
    """Amounts converted into the target currency.

    `frame` has the converted amount columns (null where no rate applied), `rate` and
    `rate_flag`. `not_converted` lists, per currency, the rows left in original currency and
    the totals of their amounts in original currency.
    """

    frame: pl.DataFrame
    not_converted: pl.DataFrame

    def flagged(self) -> pl.DataFrame:
        """Number of rows per fallback flag."""
        return (
            self.frame.filter(pl.col("rate_flag") != "")
            .group_by("rate_flag")
            .agg(pl.len().alias("rows"))
            .sort("rate_flag")
        )


def convert(
    frame: pl.DataFrame,
    columns: list[str],
    *,
    day: str,
    rule: Rule,
    target: str,
    market: MarketData | None,
    max_lookback_days: int = MAX_LOOKBACK_DAYS,
    currency: str = "currency",
) -> Conversion:
    """Convert the amount `columns` of every row into `target` by the CV01 rule `rule`.

    `day` names the date column: the booking date for flows, the valuation date for stocks;
    for a flow derived from two valuations, any date of its booking month.
    """
    keyed = frame.with_columns(pl.col(currency).alias("currency"), pl.col(day).alias("day")).select(
        "currency", "day"
    )
    rates = lookup_rates(market, target, keyed, rule, max_lookback_days)
    joined = frame.with_columns(
        pl.col(currency).alias("_currency"), pl.col(day).alias("_day")
    ).join(
        rates.rename({"currency": "_currency", "day": "_day", "flag": "rate_flag"}),
        on=["_currency", "_day"],
        how="left",
    )
    converted = joined.with_columns(*[(pl.col(c) * pl.col("rate")).alias(c) for c in columns]).drop(
        "_currency", "_day"
    )
    left = joined.filter(pl.col("rate").is_null())
    totals = left.group_by(currency).agg(
        pl.len().alias("rows"), *[pl.col(c).sum().alias(c) for c in columns]
    )
    return Conversion(converted, totals.sort(currency))
