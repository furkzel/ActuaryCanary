"""Ledger balances as the platform's amounts (CV12, record 0421): the sign of the profile, and
year-to-date income and expense balances turned into monthly movements by differencing within the
fiscal year. Balance-sheet accounts (a PERIOD balance) are stocks and stay as they are.
"""

import polars as pl

from actuarycanary.ledger.profile import Assignment

_COLUMNS = ["entity", "account", "period", "account_class", "balance_kind", "sign", "line"]


def _months(period: pl.Expr) -> pl.Expr:
    return period.dt.year() * 12 + period.dt.month() - 1


def mapped_amounts(
    ledger: pl.DataFrame, assignment: Assignment, fiscal_year_start_month: int = 1
) -> pl.DataFrame:
    """One row per mapped account, entity and month: `amount` (the monthly movement of a flow,
    the balance of a stock, in the ledger's sign) and `signed` (times the profile's sign, the
    platform's amount). The amount of a year-to-date row is null when the month before it is
    missing and the row has no opening balance: the movement cannot be told.

    Rows of accounts the profile does not map, or maps ambiguously, are not in the result."""
    rules = pl.DataFrame(
        [
            {
                "entity": e,
                "account": a,
                "account_class": r.account_class,
                "balance_kind": r.balance_kind,
                "sign": r.sign,
                "line": r.line,
            }
            for (e, a), r in assignment.rules.items()
        ],
        schema={
            "entity": pl.String,
            "account": pl.String,
            "account_class": pl.String,
            "balance_kind": pl.String,
            "sign": pl.Int64,
            "line": pl.String,
        },
    )
    opening = pl.col("opening_balance") if "opening_balance" in ledger.columns else pl.lit(None)
    currency = pl.col("currency") if "currency" in ledger.columns else pl.lit("")
    rows = (
        ledger.select(
            "entity",
            "account",
            "period",
            "closing_balance",
            opening.cast(pl.Float64).alias("opening_balance"),
            currency.fill_null("").alias("currency"),
        )
        .join(rules, on=["entity", "account"], how="inner")
        .sort("entity", "account", "currency", "period")
        .with_columns(
            pl.col("closing_balance").shift(1).over("entity", "account", "currency").alias("_prev"),
            _months(pl.col("period"))
            .shift(1)
            .over("entity", "account", "currency")
            .alias("_prev_month"),
        )
    )
    previous = (
        pl.when(_months(pl.col("period")) - pl.col("_prev_month") == 1)
        .then(pl.col("_prev"))
        .otherwise(pl.col("opening_balance"))
    )
    movement = (
        pl.when(pl.col("period").dt.month() == fiscal_year_start_month)
        .then(pl.col("closing_balance"))
        .otherwise(pl.col("closing_balance") - previous)
    )
    rows = rows.with_columns(
        pl.when(pl.col("balance_kind") == "YEAR_TO_DATE")
        .then(movement)
        .otherwise(pl.col("closing_balance"))
        .alias("amount")
    ).with_columns((pl.col("amount") * pl.col("sign")).alias("signed"))
    return rows.select(*_COLUMNS, "amount", "signed").sort("entity", "account", "period")
