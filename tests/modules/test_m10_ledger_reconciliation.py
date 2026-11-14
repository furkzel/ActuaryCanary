"""M10 Ledger reconciliation: the module in the runner on hand feeds, its tables, the skip reason
of its specification, and the run without a ledger as it was before."""

from datetime import date

import polars as pl

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.ledger.profile import (
    AccountProfile,
    AccountRule,
    ProfileInUse,
    chart_fingerprint,
)
from actuarycanary.ledger.settings import LedgerSettings
from actuarycanary.measures.ledger_measures import RUN_KEY, LedgerRun
from actuarycanary.modules.ledger_reconciliation import ledger_tables, mapping_label
from actuarycanary.modules.runner import ModuleState, run_modules
from actuarycanary.modules.views import views_of
from actuarycanary.quality.engine import evaluate
from actuarycanary.structures.periods import Period
from tests.measures.helpers import CATALOGUE, make_inputs
from tests.quality.builders import balance, cv, expense, policy, premium

M10 = CATALOGUE.modules["M10"]
CUT_OFF = date(2024, 3, 31)


def rules(*pairs: tuple[str, str, int]) -> list[AccountRule]:
    return [
        AccountRule(pattern=p, account_class=c, sign=s, balance_kind="PERIOD")  # type: ignore[arg-type]
        for p, c, s in pairs
    ]


def profile(*pairs: tuple[str, str, int], confirmed_on: date | None = None) -> AccountProfile:
    chosen = rules(*pairs)
    codes = [r.pattern for r in chosen]
    return AccountProfile(
        fingerprint=chart_fingerprint([*codes, "297"]),
        accounts=[*codes, "297"],
        rules=chosen,
        confirmed_on=confirmed_on,
    )


def rows(premiums: list[float]) -> dict:
    return {
        "claim_valuations": [cv(1)],
        "policies": [policy(entity="E")],
        "premiums": [
            premium(transaction_id=f"T{i}", booking_date=date(2024, i, 5), amount=v)
            for i, v in enumerate(premiums, start=1)
        ],
        "expenses": [
            expense(period=d, amount=50.0, entity="E")
            for d in (date(2024, m, 28) for m in (1, 2, 3))
        ],
        "ledger": [
            *[balance(m, account="600", closing_balance=-1000.0) for m in (1, 2, 3)],
            *[balance(m, account="770", closing_balance=50.0) for m in (1, 2, 3)],
            *[balance(m, account="297", closing_balance=1000.0 * (m == 3)) for m in (1, 2, 3)],
        ],
    }


def run(feeds: dict, mapped: AccountProfile | None = None):
    inputs = make_inputs(feeds, cut_off=CUT_OFF)
    if mapped is not None:
        inputs.cache[RUN_KEY] = LedgerRun(
            ProfileInUse(mapped, "a" * 64, None, False), LedgerSettings()
        )
    loaded = {
        c: CanonicalFeed(c, "1", f, tuple(x for x in f.columns if not x.startswith("_")), ())
        for c, f in inputs.feeds.items()
    }
    quality = evaluate(
        CATALOGUE, loaded, dict(inputs.feeds), cut_off=CUT_OFF, account_profile=mapped
    )
    analysis = run_modules(
        CATALOGUE, inputs, quality, Period.YEAR, ReinsuranceBasis.GROSS, ValueBasis.NOMINAL
    )
    return analysis, inputs


MAPPED = profile(("600", "PREMIUM", -1), ("770", "EXPENSE", 1))


def test_the_specification_lists_two_measures_and_needs_a_ledger_and_a_feed() -> None:
    assert M10.measures == ["FN01", "FN02"] and M10.methods == []
    assert M10.required_all == ["ledger"] and M10.implemented and M10.status == "draft"
    assert "premiums.xlsx" in M10.skip_reason and "ledger.xlsx" in M10.skip_reason


def test_the_module_asks_one_view_by_entity_class_and_month_and_one_by_entity_and_month() -> None:
    fn01, fn02 = views_of("M10", "FN01"), views_of("M10", "FN02")
    assert [(v.breakdowns, v.period) for v in fn01] == [
        (("entity", "account_class", "calendar_period"), Period.MONTH)
    ]
    assert [(v.breakdowns, v.period) for v in fn02] == [
        (("entity", "calendar_period"), Period.MONTH)
    ]


def test_with_a_ledger_and_feeds_both_measures_are_computed() -> None:
    analysis, _ = run(rows([1000.0, 1000.0, 1010.0]), MAPPED)
    outcome = analysis.get("M10")
    assert outcome.state in (ModuleState.RAN, ModuleState.LIMITED)
    assert {m.measure for m in outcome.available} == {"FN01", "FN02"}


def test_without_a_ledger_the_module_is_skipped_with_its_reason() -> None:
    feeds = rows([1000.0] * 3)
    del feeds["ledger"]
    analysis, _ = run(feeds)
    outcome = analysis.get("M10")
    assert outcome.state is ModuleState.SKIPPED
    assert outcome.reasons[0].startswith("Ledger reconciliation did not run")


def test_a_ledger_alone_is_not_enough_to_run() -> None:
    analysis, _ = run({"policies": [policy(entity="E")], "ledger": rows([1.0])["ledger"]})
    assert analysis.get("M10").state is ModuleState.SKIPPED


def test_the_tables_name_the_material_gap_the_unmapped_account_and_the_profile_state() -> None:
    _, inputs = run(rows([1000.0, 1000.0, 1010.0]), MAPPED)
    tables = ledger_tables(inputs)
    material = tables.material
    assert [
        (r["account_class"], r["period"], r["gap"]) for r in material.iter_rows(named=True)
    ] == [("PREMIUM", date(2024, 3, 31), 10.0)]
    assert material["suggested_causes"][0] == "no cause suggested"
    assert tables.unmapped.height == 1
    row = tables.unmapped.row(0, named=True)
    assert (row["account"], row["latest_balance"], row["months_with_balance"]) == ("297", 1000.0, 1)
    assert "no rule" in row["reason"]
    share = {r["period"]: r["value"] for r in tables.share.iter_rows(named=True)}
    assert share[date(2024, 1, 31)] == 0.0
    assert abs(share[date(2024, 3, 31)] - 1000.0 / (1000 + 1000 + 50)) < 1e-12
    assert tables.mapping == "proposed, not confirmed"
    assert set(tables.reconciliation["ledger_mapping"]) == {"proposed, not confirmed"}


def test_a_confirmed_profile_is_named_with_its_date_on_every_figure() -> None:
    confirmed = profile(("600", "PREMIUM", -1), confirmed_on=date(2026, 11, 14))
    _, inputs = run(rows([1000.0] * 3), confirmed)
    assert mapping_label(confirmed) == "confirmed on 2026-11-14"
    assert set(ledger_tables(inputs).reconciliation["ledger_mapping"]) == {
        "confirmed on 2026-11-14"
    }


def test_a_tie_of_two_rules_is_listed_with_its_patterns_and_leaves_the_account_out() -> None:
    tied = AccountProfile(
        fingerprint=chart_fingerprint(["600", "770", "297"]),
        accounts=["297", "600", "770"],
        rules=[
            *rules(("600*", "PREMIUM", -1), ("770", "EXPENSE", 1)),
            *rules(("600*", "OTHER", 1)),
        ],
    )
    _, inputs = run(rows([1000.0] * 3), tied)
    tables = ledger_tables(inputs)
    listed = {r["account"]: r["reason"] for r in tables.unmapped.iter_rows(named=True)}
    assert "600*, 600*" in listed["600"] and "same precedence" in listed["600"]
    assert "PREMIUM" not in set(tables.reconciliation["account_class"])


def test_the_run_without_a_ledger_has_the_files_and_manifest_it_had(default_run) -> None:
    names = {p.name for p in default_run.folder.iterdir()}
    assert not {"reconciliation.csv", "unmapped_accounts.csv"} & names
    assert default_run.analysis.get("M10").state is ModuleState.SKIPPED
    assert "account_mapping" not in default_run.manifest.read_text(encoding="utf-8")
    assert (
        pl.read_csv(default_run.folder / "measures.csv")["measure"].str.starts_with("FN").sum() == 0
    )
