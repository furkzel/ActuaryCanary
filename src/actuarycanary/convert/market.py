"""Market series as lookup tables: exchange rates and price indices (market spec, CV01, CV02).

Exchange rates are BASE/QUOTE pairs giving QUOTE units per BASE unit, so an amount in
currency ORIG becomes an amount in TARGET when multiplied by the rate of ORIG/TARGET. When
only TARGET/ORIG exists its reciprocal is used; no cross rates are formed (CV01). Daily
kinds are keyed by date, monthly kinds (period average, period end, price index) by month
index: any date in the month stands for the month.
"""

from dataclasses import dataclass

import polars as pl

from actuarycanary.io.excel import SOURCE_ROW

FX_SPOT = "FX_SPOT"
FX_PERIOD_AVERAGE = "FX_PERIOD_AVERAGE"
FX_PERIOD_END = "FX_PERIOD_END"
PRICE_INDEX = "PRICE_INDEX"
KINDS = (FX_SPOT, FX_PERIOD_AVERAGE, FX_PERIOD_END, PRICE_INDEX)
MONTHLY_KINDS = (FX_PERIOD_AVERAGE, FX_PERIOD_END, PRICE_INDEX)


class ConversionError(Exception):
    """A conversion or restatement cannot be done with the market data given."""


def month_of(column: str) -> pl.Expr:
    return pl.col(column).dt.year().cast(pl.Int64) * 12 + pl.col(column).dt.month() - 1


@dataclass(frozen=True)
class MarketData:
    """Series by (kind, series_id), each a table of key, value sorted by key.

    The key is a date for FX_SPOT and a month index for the monthly kinds. Conflicting
    values for one key keep the later date in the month, then the later source row (the
    market spec, DV-MKT-02).
    """

    series: dict[tuple[str, str], pl.DataFrame]

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> "MarketData":
        has_row = SOURCE_ROW in frame.columns
        usable = frame.filter(
            pl.col("kind").is_in(KINDS)
            & pl.col("value").is_not_null()
            & (pl.col("value") > 0)
            & pl.col("date").is_not_null()
            & pl.col("series_id").is_not_null()
        )
        order = ["date", SOURCE_ROW] if has_row else ["date"]
        series: dict[tuple[str, str], pl.DataFrame] = {}
        for (kind, series_id), part in usable.sort(order).group_by(
            ["kind", "series_id"], maintain_order=True
        ):
            key = pl.col("date") if kind == FX_SPOT else month_of("date")
            table = (
                part.select(key.alias("key"), "value")
                .unique(subset="key", keep="last", maintain_order=True)
                .sort("key")
            )
            series[(str(kind), str(series_id))] = table
        return cls(series)

    def pair(self, kind: str, original: str, target: str) -> pl.DataFrame | None:
        """Rate table (key, rate) of ORIGINAL into TARGET, direct or by reciprocal."""
        direct = self.series.get((kind, f"{original}/{target}"))
        if direct is not None:
            return direct.rename({"value": "rate"})
        inverse = self.series.get((kind, f"{target}/{original}"))
        if inverse is not None:
            return inverse.select("key", (1.0 / pl.col("value")).alias("rate"))
        return None

    def index(self, series_id: str) -> pl.DataFrame | None:
        """Price index table (key = month index, value)."""
        return self.series.get((PRICE_INDEX, series_id))

    def has_fx(self, original: str, target: str) -> bool:
        return any(
            self.pair(kind, original, target) is not None
            for kind in (FX_SPOT, FX_PERIOD_AVERAGE, FX_PERIOD_END)
        )
