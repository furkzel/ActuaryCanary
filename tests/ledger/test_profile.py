"""The account-mapping profile (CV12): patterns, precedence, the file and its fingerprint."""

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from actuarycanary.ledger.classes import class_of_name
from actuarycanary.ledger.profile import (
    AccountProfile,
    AccountRule,
    assign,
    chart_fingerprint,
    dump_profile,
    profile_path,
    profile_sha256,
    read_profile,
    save_profile,
)
from actuarycanary.ledger.resolve import profile_in_use
from actuarycanary.recognition.mapping_profiles import ProfileError

CHART = ["600", "600.01.001", "600.01.002", "700", "297"]


def rule(
    pattern: str, account_class: Any = "PREMIUM", entity: str | None = None, **more: Any
) -> AccountRule:
    values = {"sign": -1, "balance_kind": "PERIOD", **more}
    return AccountRule(entity=entity, pattern=pattern, account_class=account_class, **values)


def profile(*rules: AccountRule, accounts: list[str] = CHART) -> AccountProfile:
    return AccountProfile(
        fingerprint=chart_fingerprint(accounts), accounts=accounts, rules=list(rules)
    )


def klass(p: AccountProfile, account: str, entity: str = "E") -> str | None:
    found = winner(p, account, entity)[0]
    return found.account_class if found else None


def winner(p: AccountProfile, account: str, entity: str = "E"):
    found = assign(p, [(entity, account)])
    return found.rules.get((entity, account)), found


def test_an_exact_pattern_and_a_prefix_match_as_cv12_says() -> None:
    p = profile(rule("600*"), rule("700", "CLAIMS_PAID", sign=1))
    assert klass(p, "600.01.001") == "PREMIUM"
    assert klass(p, "600") == "PREMIUM"  # a prefix matches its own code
    assert klass(p, "700") == "CLAIMS_PAID"
    assert winner(p, "7001")[0] is None  # an exact pattern is not a prefix


def test_the_longest_pattern_wins() -> None:
    p = profile(rule("600*"), rule("600.01*", "COMMISSION", sign=1))
    assert klass(p, "600.01.002") == "COMMISSION"
    assert klass(p, "600.02") == "PREMIUM"


def test_an_exact_code_beats_a_prefix_of_the_same_length_and_an_entity_beats_all() -> None:
    p = profile(rule("600*"), rule("600", "OTHER", sign=1))
    assert klass(p, "600") == "OTHER"
    assert klass(p, "600.1") == "PREMIUM"
    q = profile(rule("600*"), rule("600*", "OTHER", entity="F", sign=1))
    assert klass(q, "600", "F") == "OTHER"
    assert klass(q, "600", "E") == "PREMIUM"


def test_two_rules_of_the_same_precedence_are_a_profile_error_for_that_account_only() -> None:
    p = profile(rule("60*"), rule("600*", "OTHER", sign=1), rule("6*", "EXPENSE", sign=1))
    chart = ["600", "601"]
    found = assign(p, [("E", a) for a in chart])
    assert found.rules[("E", "601")].account_class == "PREMIUM"  # only 60* and 6* reach it
    both = profile(rule("600*"), rule("600*", "OTHER", sign=1))
    found = assign(both, [("E", "600"), ("E", "700")])
    assert [(t.account, t.patterns) for t in found.ties] == [("600", ("600*", "600*"))]
    assert found.unmapped == (("E", "700"),) and not found.rules


def test_accounts_no_rule_matches_are_unmapped() -> None:
    found = assign(profile(rule("600*")), [("E", "600"), ("E", "297"), ("F", "297")])
    assert found.unmapped == (("E", "297"), ("F", "297"))


@pytest.mark.parametrize("pattern", ["", "6*0", "*6*"])
def test_a_pattern_is_a_code_or_a_prefix_with_one_star(pattern: str) -> None:
    with pytest.raises(ValueError):
        rule(pattern)


def test_the_fingerprint_is_that_of_the_set_of_codes_whatever_the_order() -> None:
    assert chart_fingerprint(["b", "a", "a"]) == chart_fingerprint(["a", "b"])
    assert chart_fingerprint(["a", "b"]) != chart_fingerprint(["a", "c"])
    with pytest.raises(ValueError, match="fingerprint"):
        AccountProfile(fingerprint="0" * 16, accounts=["a"], rules=[])


def test_the_file_is_saved_read_back_and_edited_by_hand(tmp_path: Path) -> None:
    p = profile(rule("600*"))
    path = save_profile(tmp_path / "profiles", p)
    assert path == profile_path(tmp_path / "profiles", p.fingerprint)
    assert path.name == f"ledger-{p.fingerprint}.yaml"
    again, sha = read_profile(path)
    assert again == p and sha == profile_sha256(p)
    assert not again.confirmed
    path.write_text(
        path.read_text(encoding="utf-8").replace("confirmed_on: null", "confirmed_on: 2026-11-14"),
        encoding="utf-8",
    )
    edited, sha_edited = read_profile(path)
    assert edited.confirmed_on == date(2026, 11, 14) and edited.confirmed
    assert sha_edited != sha  # the confirmation changes the fingerprint of the run
    assert dump_profile(edited).count("confirmed_on: 2026-11-14") == 1


def test_a_file_that_does_not_fit_is_a_profile_error(tmp_path: Path) -> None:
    bad = tmp_path / "ledger-x.yaml"
    bad.write_text("fingerprint: nope\naccounts: [a]\nrules: []\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        read_profile(bad)
    bad.write_text("rules: [not, a, rule]", encoding="utf-8")
    with pytest.raises(ProfileError):
        read_profile(bad)


def test_a_run_proposes_saves_and_then_reuses_the_profile(tmp_path: Path) -> None:
    ledger = pl.DataFrame(
        {
            "entity": ["E", "E"],
            "account": ["600", "297"],
            "period": [date(2024, 1, 31)] * 2,
            "closing_balance": [-5.0, 5.0],
            "account_class": ["PREMIUM", None],
        }
    )
    first = profile_in_use(ledger, tmp_path)
    assert not first.saved and first.path is not None and first.path.is_file()
    assert first.status == "proposed" and [r.pattern for r in first.profile.rules] == ["600"]
    again = profile_in_use(ledger, tmp_path)
    assert again.saved and again.sha256 == first.sha256 and again.profile == first.profile
    unsaved = profile_in_use(ledger, None)
    assert unsaved.path is None and unsaved.sha256 == first.sha256
    # a different chart is another file
    other = profile_in_use(ledger.filter(pl.col("account") == "600"), tmp_path)
    assert other.path != first.path


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Yazılan primler", "PREMIUM"),
        ("Kazanılmamış prim karşılığı", "UPR"),
        ("KPK", "UPR"),
        ("Muallak hasar karşılığı", "OUTSTANDING"),
        ("Ödenen hasarlar", "CLAIMS_PAID"),
        ("Reasürans komisyon geliri", "RI"),
        ("Komisyon giderleri", "COMMISSION"),
        ("Operating expenses", "EXPENSE"),
        ("Askı hesabı", None),
        ("Group premium?", None),  # "upr" is a word of its own, not part of one
        (None, None),
    ],
)
def test_account_names_point_to_a_class_through_the_tokens(name: str | None, expected) -> None:
    assert class_of_name(name) == expected
