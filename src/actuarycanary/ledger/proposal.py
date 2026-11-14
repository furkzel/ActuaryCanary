"""The first proposal of an account-mapping profile (CV12, record 0421): the class of each
account from the ledger's `account_class` column, or from the words of `account_name`; the sign
and the balance kind from the balances themselves, with the defaults of CV12 where the balances
say nothing. Accounts the proposal cannot class stay out of the profile (unmapped).
"""

from typing import Literal

import polars as pl

from actuarycanary.ledger.classes import (
    DEFAULT_SIGN,
    PERIOD,
    STOCK_CLASSES,
    YEAR_TO_DATE,
    BalanceKind,
    class_of_name,
)
from actuarycanary.ledger.profile import AccountProfile, AccountRule, chart_fingerprint

UNMAPPED = "UNMAPPED"
_INCREASING_SHARE = 0.8  # share of in-year steps that do not fall for a year-to-date account
_NO_RESTART_SHARE = 0.9  # the same when no year start can be seen
_MIN_STEPS = 3
_ZERO = 0.005  # a balance within half a cent of zero is zero


def propose_profile(frame: pl.DataFrame, fiscal_year_start_month: int = 1) -> AccountProfile:
    """The proposed profile of the chart of accounts in `frame` (a canonical ledger)."""
    accounts = sorted(frame["account"].unique().to_list())
    rules: list[AccountRule] = []
    for account in accounts:
        rows = frame.filter(pl.col("account") == account)
        account_class = _class_of(rows)
        if account_class is None:
            continue
        rules.append(
            AccountRule(
                pattern=account,
                account_class=account_class,  # type: ignore[arg-type]
                sign=_sign(rows, account_class),
                balance_kind=_balance_kind(rows, account_class, fiscal_year_start_month),
            )
        )
    return AccountProfile(fingerprint=chart_fingerprint(accounts), accounts=accounts, rules=rules)


def _class_of(rows: pl.DataFrame) -> str | None:
    if "account_class" in rows.columns:
        given = rows["account_class"].drop_nulls()
        given = given.filter(given != UNMAPPED)
        if given.len():
            return str(given.mode().sort()[0])
    if "account_name" in rows.columns:
        names = rows["account_name"].drop_nulls()
        for name in names.unique().sort().to_list():
            if (found := class_of_name(str(name))) is not None:
                return found
    return None


def _sign(rows: pl.DataFrame, account_class: str) -> Literal[1, -1]:
    """+1 when the account's balances are mostly debit, -1 when mostly credit, so that the
    platform's amount is a positive magnitude; the default of CV12 when they sum to zero."""
    total = float(rows["closing_balance"].sum())
    if abs(total) > 0:
        return 1 if total > 0 else -1
    return 1 if DEFAULT_SIGN.get(account_class, 1) > 0 else -1


def _balance_kind(rows: pl.DataFrame, account_class: str, start_month: int) -> BalanceKind:
    """Year to date when the balance climbs within a fiscal year and starts again at its start;
    stocks (outstanding, unearned premium) are never year to date."""
    if account_class in STOCK_CLASSES:
        return PERIOD
    opened = _restarts_with_opening(rows, start_month)
    if opened is not None:
        return YEAR_TO_DATE if opened else PERIOD
    series = (
        rows.select("entity", "period", pl.col("closing_balance").abs().alias("size"))
        .sort("entity", "period")
        .with_columns(
            pl.col("size").shift(1).over("entity").alias("before"),
            pl.col("period").shift(1).over("entity").alias("before_period"),
        )
        .drop_nulls("before")
    )
    month = pl.col("period").dt.month() + 12 * pl.col("period").dt.year()
    before = pl.col("before_period").dt.month() + 12 * pl.col("before_period").dt.year()
    consecutive = series.filter(month - before == 1)
    start = pl.col("period").dt.month() == start_month
    within, starts = consecutive.filter(~start), consecutive.filter(start)
    if within.height < _MIN_STEPS or (within["size"] == within["before"]).all():
        return PERIOD
    climbing = _share(within["size"] >= within["before"])
    if starts.height:
        restarts = _share(starts["size"] < starts["before"])
        return YEAR_TO_DATE if restarts >= 0.5 and climbing >= _INCREASING_SHARE else PERIOD
    return YEAR_TO_DATE if climbing >= _NO_RESTART_SHARE else PERIOD


def _restarts_with_opening(rows: pl.DataFrame, start_month: int) -> bool | None:
    """Whether the opening balance of the first fiscal month is zero after a month with a
    balance (the restart of a year-to-date account, DV-LDG-07); None when no such month is seen
    or the ledger has no opening balances."""
    if "opening_balance" not in rows.columns:
        return None
    seen = rows.sort("entity", "period").with_columns(
        pl.col("closing_balance").shift(1).over("entity").alias("before"),
        pl.col("period").shift(1).over("entity").alias("before_period"),
    )
    month = pl.col("period").dt.year() * 12 + pl.col("period").dt.month()
    before = pl.col("before_period").dt.year() * 12 + pl.col("before_period").dt.month()
    starts = seen.filter(
        (pl.col("period").dt.month() == start_month)
        & (month - before == 1)
        & (pl.col("before").abs() > _ZERO)
        & pl.col("opening_balance").is_not_null()
    )
    if starts.is_empty():
        return None
    return _share(starts["opening_balance"].abs() <= _ZERO) >= 0.5


def _share(mask: pl.Series) -> float:
    return float(mask.cast(pl.Float64).sum()) / max(mask.len(), 1)
