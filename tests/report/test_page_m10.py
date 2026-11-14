"""The M10 page in both languages and the facts of KF47 to KF49 (RP01 1.6.0, record 0425).

Spec IDs proved: M10, FN01, FN02, CV12, RP01.
"""

import re
from datetime import date
from pathlib import Path

import pytest

from actuarycanary.ledger.profile import (
    AccountProfile,
    AccountRule,
    ProfileInUse,
    chart_fingerprint,
)
from actuarycanary.ledger.settings import LedgerSettings
from actuarycanary.measures.ledger_measures import RUN_KEY, LedgerRun
from actuarycanary.modules.ledger_reconciliation import LedgerTables, ledger_tables
from actuarycanary.report import language
from actuarycanary.report.facts import FactSet
from actuarycanary.report.ledger_section import add_ledger_facts, ledger_page
from tests.measures.helpers import make_inputs
from tests.quality.builders import balance, expense, policy, premium

TEMPLATE = Path(__file__).parents[2] / "src/actuarycanary/report/templates/ledger.html.j2"
CUT_OFF = date(2024, 3, 31)


def _spec(*ids: str) -> str:
    return ", ".join(ids)


def tables(
    confirmed_on: date | None = None, settings: LedgerSettings | None = None
) -> LedgerTables:
    rules = [
        AccountRule(pattern="600", account_class="PREMIUM", sign=-1, balance_kind="PERIOD"),
        AccountRule(pattern="770", account_class="EXPENSE", sign=1, balance_kind="YEAR_TO_DATE"),
        AccountRule(pattern="360", account_class="OUTSTANDING", sign=-1, balance_kind="PERIOD"),
    ]
    codes = ["297", "360", "600", "770"]
    profile = AccountProfile(
        fingerprint=chart_fingerprint(codes), accounts=codes, rules=rules, confirmed_on=confirmed_on
    )
    feeds = {
        "policies": [policy(entity="E")],
        "premiums": [
            premium(transaction_id=f"T{m}", booking_date=date(2024, m, 5), amount=v)
            for m, v in ((1, 1000.0), (2, 1000.0), (3, 1100.0))
        ],
        "expenses": [expense(period=date(2024, m, 28), amount=50.0, entity="E") for m in (1, 2, 3)],
        "ledger": [
            *[balance(m, account="600", closing_balance=-1000.0) for m in (1, 2, 3)],
            *[
                balance(m, account="770", closing_balance=50.0 * m, account_name="Giderler")
                for m in (1, 2, 3)
            ],
            *[
                balance(m, account="297", closing_balance=200.0, account_name="Askı")
                for m in (1, 2, 3)
            ],
            *[balance(m, account="360", closing_balance=-5.0) for m in (1, 2, 3)],
        ],
    }
    inputs = make_inputs(feeds, cut_off=CUT_OFF)
    inputs.cache[RUN_KEY] = LedgerRun(
        ProfileInUse(profile, "ab" * 32, None, False), settings or LedgerSettings()
    )
    return ledger_tables(inputs)


def test_every_label_of_the_template_has_its_turkish_text() -> None:
    labels = set(re.findall(r'tr\("([^"]+)"', TEMPLATE.read_text(encoding="utf-8")))
    assert labels and labels <= set(language.catalogue())


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_the_page_asks_only_for_texts_the_resource_has(lang: str) -> None:
    with language.using(lang), language.recording() as asked:
        body = ledger_page(tables(), CUT_OFF, _spec, {}, "TRY")
    assert body["available"]
    if lang == "tr":
        assert language.untranslated(asked) == []


def test_the_page_names_the_gap_the_unmapped_account_and_the_state_of_the_profile() -> None:
    figures: dict = {}
    with language.using("en"):
        body = ledger_page(tables(), CUT_OFF, _spec, figures, "TRY")
    assert body["material"] == "1" and "PREMIUM of E, 2024-03" in body["largest"]
    assert body["profile"]["state"] == "proposed, not confirmed" and body["profile"]["proposed"]
    classes = {r["account_class"]: r for r in body["classes"]}
    assert classes["PREMIUM"]["material"] == "1" and classes["PREMIUM"]["state"] == "reconciled"
    assert classes["OUTSTANDING"]["state"] == "not reconciled"  # no claim valuations loaded
    assert "claim_valuations" in classes["OUTSTANDING"]["reason"]
    pair = body["matrix"]["rows"][0]
    assert pair["label"] == "E · PREMIUM" and [c["material"] for c in pair["cells"]] == [
        False,
        False,
        True,
    ]
    top = body["largest_gaps"][0]
    assert (top["gap"], top["causes"]) == ("100", "no cause suggested")
    assert body["unmapped"][0]["account"] == "297" and body["unmapped"][0]["name"] == "Askı"
    assert body["unmapped_share"] != "–" and "0.5%" in body["limit"]
    assert {r["pattern"] for r in body["profile"]["rules"]} == {"360", "600", "770"}
    assert {r["kind"] for r in body["profile"]["rules"]} == {"PERIOD", "YEAR_TO_DATE"}
    assert "ledger-" + body["profile"]["fingerprint"] in body["footnote"]
    traces = figures["ledger-gap-trend"]["data"]
    assert {t["name"] for t in traces} == {"EXPENSE", "PREMIUM"} and body[
        "figure"
    ] == "ledger-gap-trend"


def test_a_confirmed_profile_says_when_in_the_language_of_the_report() -> None:
    confirmed = tables(
        date(2026, 11, 14), LedgerSettings(materiality_ratio=0.01, materiality_amount=5.0)
    )
    with language.using("tr"):
        body = ledger_page(confirmed, CUT_OFF, _spec, {}, "TRY")
    assert (
        body["profile"]["state"] == "2026-11-14 tarihinde onaylandı"
        and not body["profile"]["proposed"]
    )
    assert "%1" in body["limit"] and "5" in body["limit"]


def test_the_facts_of_the_rules() -> None:
    facts: FactSet = {}
    with language.using("en"):
        add_ledger_facts(facts, tables())
    assert facts["ledger_material_gaps"].value == 1 and facts["ledger_gap_rows"].value == 6
    assert facts["ledger_gap_classes"].value == "PREMIUM 1"
    assert facts["ledger_largest_gap"].value == 100.0
    assert (facts["ledger_largest_gap_class"].value, facts["ledger_largest_gap_month"].value) == (
        "PREMIUM",
        "2024-03",
    )
    assert facts["ledger_largest_gap_cause"].value == "no cause suggested"
    assert facts["ledger_profile_proposed"].value == 1
    assert (
        facts["ledger_unmapped_entity"].value == "E"
        and facts["ledger_unmapped_accounts"].value == "297"
    )
    assert 0 < float(facts["ledger_unmapped_share"].value) < 0.3
    confirmed: FactSet = {}
    add_ledger_facts(confirmed, tables(date(2026, 11, 14)))
    assert confirmed["ledger_profile_proposed"].value == 0
    quiet: FactSet = {}
    add_ledger_facts(quiet, None)
    assert quiet == {}
