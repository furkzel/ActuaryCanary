"""Hand fixtures of market data and claim valuations in three currencies and two prices.

Index CPI_TR is 100 in 2024-01, 110 in 2024-02 and 132 in 2024-03, so restated to the prices
of 2024-03 a January amount is multiplied by 1.32 and a February amount by 1.2. TRY is the
reporting currency; USD rates are given as USD/TRY, EUR rates only as TRY/EUR (reciprocal).
"""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.convert.market import MarketData
from actuarycanary.io.excel import SOURCE_ROW

JAN, FEB, MAR = date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)

# series, kind, date, value
MARKET_ROWS: list[tuple[str, str, date, float]] = [
    ("CPI_TR", "PRICE_INDEX", JAN, 100.0),
    ("CPI_TR", "PRICE_INDEX", FEB, 110.0),
    ("CPI_TR", "PRICE_INDEX", MAR, 132.0),
    ("USD/TRY", "FX_PERIOD_AVERAGE", JAN, 30.0),
    ("USD/TRY", "FX_PERIOD_AVERAGE", FEB, 31.0),
    ("USD/TRY", "FX_PERIOD_AVERAGE", MAR, 33.0),
    ("USD/TRY", "FX_PERIOD_END", JAN, 31.0),
    ("USD/TRY", "FX_PERIOD_END", FEB, 32.0),
    ("USD/TRY", "FX_PERIOD_END", MAR, 34.0),
    ("TRY/EUR", "FX_PERIOD_AVERAGE", JAN, 0.025),  # EUR/TRY 40
    ("TRY/EUR", "FX_PERIOD_AVERAGE", FEB, 0.02),  # 50
    ("TRY/EUR", "FX_PERIOD_AVERAGE", MAR, 0.0125),  # 80
    ("TRY/EUR", "FX_PERIOD_END", JAN, 0.02),  # 50
    ("TRY/EUR", "FX_PERIOD_END", FEB, 0.016),  # 62.5
    ("TRY/EUR", "FX_PERIOD_END", MAR, 0.01),  # 100
]


def market_frame(rows: list[tuple[str, str, date, float]] = MARKET_ROWS) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "series_id": [r[0] for r in rows],
            "kind": [r[1] for r in rows],
            "date": [r[2] for r in rows],
            "value": [r[3] for r in rows],
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        },
        schema_overrides={"date": pl.Date},
    )


def market(rows: list[tuple[str, str, date, float]] = MARKET_ROWS) -> MarketData:
    return MarketData.from_frame(market_frame(rows))


# claim, currency, valuation date, paid, case reserve, ceded paid, ceded reserve
VALUATION_ROWS: list[tuple[Any, ...]] = [
    ("A", "TRY", JAN, 100.0, 50.0, 40.0, 20.0),
    ("A", "TRY", FEB, 100.0, 20.0, 40.0, 8.0),
    ("A", "TRY", MAR, 300.0, 0.0, 120.0, 0.0),
    ("B", "USD", JAN, 10.0, 5.0, 0.0, 0.0),
    ("B", "USD", MAR, 30.0, 0.0, 0.0, 0.0),
    ("C", "EUR", FEB, 0.0, 8.0, 0.0, 4.0),
    ("C", "EUR", MAR, 4.0, 2.0, 2.0, 1.0),
]


def valuations(rows: list[tuple[Any, ...]] = VALUATION_ROWS) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "claim_id": [r[0] for r in rows],
            "currency": [r[1] for r in rows],
            "valuation_date": [r[2] for r in rows],
            "paid_to_date": [r[3] for r in rows],
            "case_reserve": [r[4] for r in rows],
            "ceded_paid_to_date": [r[5] for r in rows],
            "ceded_reserve": [r[6] for r in rows],
            "status": ["OPEN"] * len(rows),
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        },
        schema_overrides={"valuation_date": pl.Date},
    )
