"""Ledger balances as the platform's amounts: sign, year-to-date differencing, stocks."""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.ledger.balances import mapped_amounts
from actuarycanary.ledger.profile import AccountProfile, AccountRule, assign, chart_fingerprint


def month_end(year: int, month: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def amounts(rows: list[tuple], rules: list[AccountRule], start: int = 1) -> pl.DataFrame:
    frame = pl.DataFrame(
        rows,
        schema=["entity", "account", "period", "closing_balance", "opening_balance"],
        orient="row",
    )
    accounts = sorted(frame["account"].unique().to_list())
    profile = AccountProfile(
        fingerprint=chart_fingerprint(accounts), accounts=accounts, rules=rules
    )
    pairs = [(e, a) for e, a in frame.select("entity", "account").unique().iter_rows()]
    return mapped_amounts(frame, assign(profile, pairs), start)


def ytd(pattern: str = "600", sign: Any = -1, cls: Any = "PREMIUM") -> AccountRule:
    return AccountRule(pattern=pattern, account_class=cls, sign=sign, balance_kind="YEAR_TO_DATE")


def test_a_two_year_year_to_date_series_is_differenced_within_each_fiscal_year() -> None:
    # year to date, credit: 10, 25, 45 in 2023 (Nov, Dec of 2022 first), restart in January
    series = [
        (2022, 11, -7.0),
        (2022, 12, -9.0),
        (2023, 1, -10.0),
        (2023, 2, -25.0),
        (2023, 3, -45.0),
    ]
    rows = [("E", "600", month_end(y, m), v, None) for y, m, v in series]
    out = amounts(rows, [ytd()]).sort("period")
    # the first month has no month before it and no opening balance: not told; then the movements,
    # and January is the balance itself (the restart)
    assert out["amount"].to_list() == [None, -2.0, -10.0, -15.0, -20.0]
    assert out["signed"].to_list() == [None, 2.0, 10.0, 15.0, 20.0]


def test_the_first_month_uses_the_opening_balance_when_the_month_before_is_missing() -> None:
    rows = [
        ("E", "600", month_end(2023, 4), -30.0, -22.0),
        ("E", "600", month_end(2023, 6), -50.0, -41.0),
    ]
    out = amounts(rows, [ytd()]).sort("period")
    assert out["amount"].to_list() == [-8.0, -9.0]


def test_a_fiscal_year_that_starts_in_april_restarts_in_april() -> None:
    rows = [
        ("E", "600", month_end(2023, m), -float(v), None) for m, v in ((3, 90), (4, 5), (5, 12))
    ]
    out = amounts(rows, [ytd()], start=4).sort("period")
    assert out["signed"].to_list() == [None, 5.0, 7.0]


def test_stocks_are_taken_at_the_period_end_with_the_sign_of_the_profile() -> None:
    stock = AccountRule(pattern="360", account_class="OUTSTANDING", sign=-1, balance_kind="PERIOD")
    rows = [("E", "360", month_end(2023, m), -float(v), None) for m, v in ((1, 100), (2, 80))]
    out = amounts(rows, [stock]).sort("period")
    assert out["amount"].to_list() == [-100.0, -80.0]
    assert out["signed"].to_list() == [100.0, 80.0]
    assert out["account_class"].unique().to_list() == ["OUTSTANDING"]


def test_unmapped_accounts_are_left_out() -> None:
    rows = [("E", "600", month_end(2023, 1), -5.0, 0.0), ("E", "297", month_end(2023, 1), 5.0, 0.0)]
    assert amounts(rows, [ytd()])["account"].to_list() == ["600"]
