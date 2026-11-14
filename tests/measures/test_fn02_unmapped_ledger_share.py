"""FN02 (CV12): how much of the books the account-mapping profile cannot see."""

from datetime import date

import pytest

from actuarycanary.ledger.profile import (
    AccountProfile,
    AccountRule,
    ProfileInUse,
    chart_fingerprint,
)
from actuarycanary.ledger.settings import LedgerSettings
from actuarycanary.measures.ledger_measures import RUN_KEY, LedgerRun
from tests.measures.helpers import make_inputs, measure
from tests.quality.builders import balance


def inputs_with(rows: list[dict], *patterns: tuple[str, str]):
    rules = [
        AccountRule(pattern=p, account_class=c, sign=1, balance_kind="PERIOD")  # type: ignore[arg-type]
        for p, c in patterns
    ]
    codes = [p for p, _ in patterns]
    profile = AccountProfile(fingerprint=chart_fingerprint(codes), accounts=codes, rules=rules)
    inputs = make_inputs({"ledger": rows}, cut_off=date(2024, 3, 31))
    inputs.cache[RUN_KEY] = LedgerRun(
        ProfileInUse(profile, "0" * 64, None, False), LedgerSettings()
    )
    return inputs


def shares(inputs) -> dict[str, float | None]:
    result = measure(inputs, "FN02", "entity", "calendar_period")
    assert result.frame is not None, result.reason
    return dict(result.frame.select("calendar_period", "value").iter_rows())


def test_balances_100_minus_50_and_50_with_the_last_account_unmapped_give_a_quarter() -> None:
    rows = [
        balance(account="100", closing_balance=100.0),
        balance(account="200", closing_balance=-50.0),
        balance(account="300", closing_balance=50.0),
    ]
    assert shares(inputs_with(rows, ("100", "PREMIUM"), ("200", "EXPENSE"))) == {"2024-01": 0.25}


def test_accounts_mapped_to_investment_or_other_count_as_mapped() -> None:
    rows = [
        balance(account="100", closing_balance=100.0),
        balance(account="660", closing_balance=-40.0),
    ]
    assert shares(inputs_with(rows, ("100", "PREMIUM"), ("660", "INVESTMENT"))) == {"2024-01": 0.0}


def test_a_month_in_which_all_balances_are_zero_is_not_computed() -> None:
    rows = [
        balance(1, closing_balance=0.0),
        balance(2, closing_balance=10.0),
        balance(2, account="9", closing_balance=10.0),
    ]
    result = measure(inputs_with(rows, ("100", "PREMIUM")), "FN02", "entity", "calendar_period")
    assert result.frame is not None
    by_month = {r["calendar_period"]: r for r in result.frame.iter_rows(named=True)}
    assert by_month["2024-01"]["value"] is None and "zero" in by_month["2024-01"]["note"]
    assert by_month["2024-02"]["value"] == 0.5


def test_a_month_the_ledger_has_no_row_for_is_absent_not_zero() -> None:
    rows = [
        balance(1, account="9", closing_balance=1.0),
        balance(3, account="9", closing_balance=1.0),
    ]
    assert set(shares(inputs_with(rows, ("100", "PREMIUM")))) == {"2024-01", "2024-03"}


def test_two_rules_that_claim_an_account_equally_leave_it_unmapped() -> None:
    rules = [
        AccountRule(pattern="1*", account_class="PREMIUM", sign=1, balance_kind="PERIOD"),
        AccountRule(pattern="1*", account_class="EXPENSE", sign=1, balance_kind="PERIOD"),
    ]
    profile = AccountProfile(fingerprint=chart_fingerprint(["100"]), accounts=["100"], rules=rules)
    inputs = make_inputs(
        {"ledger": [balance(account="100", closing_balance=5.0)]}, cut_off=date(2024, 3, 31)
    )
    inputs.cache[RUN_KEY] = LedgerRun(
        ProfileInUse(profile, "0" * 64, None, False), LedgerSettings()
    )
    assert shares(inputs) == pytest.approx({"2024-01": 1.0})
