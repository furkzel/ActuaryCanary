"""The proposal of an account-mapping profile against the generator's own profile (record 0244),
and the data rule DV-LDG-09 that rests on it."""

import polars as pl
import pytest

from actuarycanary.ledger.profile import AccountProfile, AccountRule, assign, chart_fingerprint
from actuarycanary.ledger.proposal import propose_profile


@pytest.fixture(scope="module")
def tiny_ledger(scenario_folder) -> tuple[pl.DataFrame, pl.DataFrame]:
    folder = scenario_folder("baseline")
    return (
        pl.read_parquet(folder / "canonical" / "ledger.parquet"),
        pl.read_csv(
            folder / "truth" / "ledger_mapping_profile.csv", schema_overrides={"entity": pl.String}
        ),
    )


def written_profile(truth: pl.DataFrame, accounts: list[str]) -> AccountProfile:
    rules = [
        AccountRule(
            entity=r["entity"],
            pattern=r["account_pattern"],
            account_class=r["account_class"],
            sign=r["sign"],
            balance_kind=r["balance_kind"],
            line=r["line"],
        )
        for r in truth.iter_rows(named=True)
    ]
    return AccountProfile(fingerprint=chart_fingerprint(accounts), accounts=accounts, rules=rules)


def resolved(profile: AccountProfile, accounts: list[str]) -> dict[str, tuple]:
    found = assign(profile, [("E", a) for a in accounts])
    return {a: (r.account_class, r.sign, r.balance_kind) for (_, a), r in found.rules.items()}


def test_the_proposal_reproduces_the_profile_of_the_generator(tiny_ledger) -> None:
    ledger, truth = tiny_ledger
    accounts = sorted(ledger["account"].unique().to_list())
    proposal = propose_profile(ledger)
    assert not proposal.confirmed
    written = written_profile(truth, accounts)
    assert resolved(proposal, accounts) == resolved(written, accounts)
    assert "297" not in resolved(proposal, accounts)  # the suspense account stays unmapped


def test_without_the_class_column_the_names_give_the_same_classes(tiny_ledger) -> None:
    ledger, truth = tiny_ledger
    accounts = sorted(ledger["account"].unique().to_list())
    proposal = propose_profile(ledger.drop("account_class"))
    assert resolved(proposal, accounts) == resolved(written_profile(truth, accounts), accounts)


def test_the_balance_kind_follows_the_balances_when_nothing_else_says(tiny_ledger) -> None:
    ledger, _ = tiny_ledger
    bare = propose_profile(ledger.drop("opening_balance", "debit", "credit"))
    kinds = {r.pattern: r.balance_kind for r in bare.rules}
    assert kinds["600"] == "YEAR_TO_DATE" and kinds["700"] == "YEAR_TO_DATE"
    assert kinds["360"] == "PERIOD" and kinds["340"] == "PERIOD" and kinds["100"] == "PERIOD"


def test_the_ledger_rule_ldg_09_lists_the_suspense_account_with_its_balance(
    scenario_checked,
) -> None:
    _, report = scenario_checked("baseline")
    found = next(f for f in report.findings if f.rule == "DV-LDG-09")
    assert found.count == 1 and found.checked > 10
    assert "297" in found.message and "proposal is used" in found.message
    assert "FN02" in found.message
    assert not any(why == "DV-LDG-09" for why, _ in report.not_evaluated)
