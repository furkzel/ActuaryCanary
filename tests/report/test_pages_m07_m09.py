"""The report pages of M07 (recoveries) and M09 (expenses), the facts and the seven finding rules
of RP01 1.3.0 (KF35 to KF41, record 0388), and the wiring of both modules into a run."""

import json
from datetime import date

import pytest

from actuarycanary.modules.expenses import expense_table
from actuarycanary.modules.recoveries import recovery_tables
from actuarycanary.report import language
from actuarycanary.report.expenses_section import add_expense_facts, expenses_page, window_ratio
from actuarycanary.report.findings import Fact, evaluate
from actuarycanary.report.recoveries_section import add_recovery_facts, recoveries_page
from actuarycanary.spec.loader import load_specs
from tests.measures.recovery_fixtures import BOOKINGS, SUB, book, booking
from tests.modules.test_m09_expenses import FULL
from tests.modules.test_m09_expenses import _run as run_m09

RULES = {r.id: r for r in load_specs().finding_rules.rules}
SETTINGS = load_specs().finding_rules.settings
NEW = ("KF35", "KF36", "KF37", "KF38", "KF39", "KF40", "KF41")


def spec(*ids: str) -> str:
    return "(" + ", ".join(ids) + ")"


def fired(rule: str, **facts: Fact) -> list[str]:
    limits = {name: Fact(value, "factor") for name, value in SETTINGS.items()}
    found = evaluate([RULES[rule]], {"run": [("", "", {**limits, **facts})]})
    return [f.text for f in found]


def analysis_of(inputs):
    from actuarycanary.canonical.feeds import CanonicalFeed
    from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
    from actuarycanary.modules.runner import run_modules
    from actuarycanary.quality.engine import evaluate as quality_of
    from actuarycanary.structures.periods import Period
    from tests.measures.helpers import CATALOGUE

    feeds = {
        c: CanonicalFeed(c, "1", f, tuple(x for x in f.columns if not x.startswith("_")), ())
        for c, f in inputs.feeds.items()
    }
    quality = quality_of(CATALOGUE, feeds, dict(inputs.feeds), cut_off=inputs.cut_off)
    return run_modules(
        CATALOGUE, inputs, quality, Period.YEAR, ReinsuranceBasis.GROSS, ValueBasis.NOMINAL
    )


# --- M07 ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recoveries():
    inputs = book(BOOKINGS)
    return analysis_of(inputs), recovery_tables(inputs)


def test_the_recoveries_page_shows_types_origins_delays_and_the_source(recoveries) -> None:
    analysis, tables = recoveries
    figures: dict = {}
    body = recoveries_page(analysis, tables, spec, figures, "TRY")
    total = next(r for r in body["headline"] if r["type"] == "All recoveries")
    # recovered 60 + 15 + 0 at the latest diagonal, paid 300 + 150 + 80
    assert total["recovered"] == "75" and total["share"] == "14.2%"
    assert total["last"] == "45"  # 30 for 2022 and 15 for 2023 in the last development year
    (line,) = body["lines"]
    assert line["line"] == "NON_LIFE · L"
    assert [(r["origin"], r["age"], r["total"]) for r in line["rows"]] == [
        ("2022", "36", "20.0%"),
        ("2023", "24", "10.0%"),
        ("2024", "12", "0.0%"),
    ]
    assert line["rows"][0]["subrogation"] == "13.3%"  # RC01: 40 of 300
    assert {r["type"] for r in body["delays"]} == {"Subrogation", "Salvage"}
    assert body["source"] == "recovery transactions"
    assert body["reconciled"] and body["differences"] == "0" and body["compared"] == "14"
    assert set(figures) == {
        "recoveries-recovery_subrogation",
        "recoveries-recovery_salvage",
        "recoveries-total",
    }
    heat = figures["recoveries-total"]["data"][0]
    assert heat["y"] == ["2022", "2023", "2024"] and heat["z"][0] == [0.1, 0.15, 0.2]


def test_the_recoveries_page_lists_the_differences_of_the_reconciliation() -> None:
    bookings = [*BOOKINGS[:3], booking(4, "B", date(2024, 5, 5), 12.0, SUB)]
    inputs = book(bookings)
    body = recoveries_page(analysis_of(inputs), recovery_tables(inputs), spec, {}, "TRY")
    assert body["differences"] == "1"
    assert body["reconciliation"] == [
        {
            "claim": "B",
            "type": "Subrogation",
            "date": "2024-05-31",
            "booked": "12",
            "to_date": "15",
            "difference": "−3",
        }
    ]


def test_the_recoveries_page_of_derived_flows_says_so() -> None:
    inputs = book(None)
    body = recoveries_page(analysis_of(inputs), recovery_tables(inputs), spec, {}, "TRY")
    assert body["source"] == "derived from the to-date fields of claim valuations"
    assert not body["reconciled"] and "nothing to reconcile" in body["reconciliation_note"]
    assert "All recoveries" in {r["type"] for r in body["headline"]}


def test_recovery_facts(recoveries) -> None:
    analysis, tables = recoveries
    facts: dict = {}
    add_recovery_facts(facts, analysis, tables)
    assert facts["recovered_to_date"].value == 75.0
    assert facts["recovery_share"].value == pytest.approx(75 / 530)
    assert facts["recovery_source"].value == "recovery transactions"
    assert (
        facts["recovery_differences"].value == 0
        and facts["recovery_valuations_compared"].value == 14
    )
    # at 12 months: 2024 recovered 0 of 80, the earlier origins 10 of 150
    assert facts["recovery_first_age"].value == 12
    assert facts["recovery_latest_origin"].value == "2024"
    assert facts["recovery_ratio_earlier"].value == pytest.approx(10 / 150)
    assert facts["recovery_ratio_drop"].value == pytest.approx(1.0)


def test_kf35_recoveries_to_date() -> None:
    facts = {
        "recovered_to_date": Fact(931702.0, "amount"),
        "recovery_share": Fact(0.0081, "ratio"),
        "recovery_source": Fact("recovery transactions", "text"),
        "currency": Fact("TRY", "text"),
    }
    assert fired("KF35", **facts) == [
        "Recoveries to date are 931,702 TRY, 0.8% of claims paid (source: recovery transactions)."
    ]
    assert fired("KF35", **{**facts, "recovered_to_date": Fact(0.0, "amount")}) == []
    with language.using("tr"):
        (text,) = fired("KF35", **facts)
        assert text.startswith("Bugüne kadarki rücu ve sovtaj tahsilatı 931.702 TRY")


def test_kf36_transactions_differ_from_the_to_date_fields() -> None:
    facts = {
        "recovery_differences": Fact(3.0, "count"),
        "recovery_valuations_compared": Fact(2484.0, "count"),
    }
    (text,) = fired("KF36", **facts)
    assert "at 3 of 2,484 valuations; the transactions are used" in text
    assert fired("KF36", **{**facts, "recovery_differences": Fact(0.0, "count")}) == []


def test_kf37_weaker_recovery_in_the_latest_origin_at_the_limit() -> None:
    assert SETTINGS["recovery_drop_limit"] == 0.5
    facts = {
        "recovery_first_age": Fact(12.0, "count"),
        "recovery_latest_origin": Fact("2025", "text"),
        "recovery_ratio_latest": Fact(0.02, "ratio"),
        "recovery_ratio_earlier": Fact(0.04, "ratio"),
        "recovery_ratio_drop": Fact(0.5, "ratio"),
    }
    (text,) = fired("KF37", **facts)
    assert text.startswith("At 12 months of development the origin 2025 has recovered 2.0% of paid")
    assert fired("KF37", **{**facts, "recovery_ratio_drop": Fact(0.49, "ratio")}) == []
    del facts["recovery_ratio_drop"]  # a rule whose condition is not known does not fire
    assert fired("KF37", **facts) == []


# --- M09 ------------------------------------------------------------------------------------


def test_the_ratio_of_a_window_needs_every_month() -> None:
    import polars as pl

    frame = pl.DataFrame(
        {
            "calendar_period": ["2024-01", "2024-02", "2024-03"],
            "numerator": [10.0, 20.0, 30.0],
            "denominator": [100.0, 100.0, 200.0],
        }
    )
    assert window_ratio(frame, ["2024-01", "2024-02", "2024-03"]) == pytest.approx(0.15)
    assert window_ratio(frame, ["2023-12", "2024-01"]) is None  # December is not there
    assert window_ratio(frame.with_columns(pl.lit(0.0).alias("denominator")), ["2024-01"]) is None


def test_the_expenses_page_shows_unit_costs_and_the_expenses_without_a_line() -> None:
    analysis, inputs = run_m09(FULL)
    table = expense_table(inputs)
    figures: dict = {}
    body = expenses_page(analysis, table, date(2024, 3, 31), spec, figures, "TRY")
    assert [r["measure"] for r in body["headline"]] == [
        "EX02 Expense ratio",
        "EX01 Commission ratio",
    ]
    assert body["headline"][0]["now"] == "–"  # three months of data are no twelve-month window
    assert [r["period"] for r in body["unit_costs"]] == ["2024"]
    (unit,) = body["unit_costs"]
    # administration is booked in every month from January to March, 140 in all, one policy
    assert unit["per_policy"] == "140" and "EX05: first period of the file" in unit["note"]
    assert [(r["type"], r["level"], r["amount"]) for r in body["unallocated"]] == [
        ("ACQUISITION", "segment LIFE", "20"),
        ("ADMINISTRATION", "not allocated", "50"),
        ("CLAIMS_HANDLING_UNALLOCATED", "not allocated", "9"),
    ]
    assert not body["priced"]  # no price index: no column at value-date prices
    assert body["unit_basis"] == "GROSS, REPORTING, NOMINAL"


def test_expense_facts() -> None:
    analysis, inputs = run_m09(FULL)
    facts: dict = {}
    add_expense_facts(facts, analysis, expense_table(inputs), date(2024, 3, 31))
    assert "expense_ratio_12m" not in facts  # no twelve months before the cut-off
    assert facts["unallocated_expenses"].value == 79.0
    assert facts["unallocated_expense_share"].value == pytest.approx(79 / 169)
    assert facts["unit_cost_periods"].value == 1 and facts["unit_cost_periods_missing"].value == 0


@pytest.mark.parametrize(("rule", "name"), [("KF38", "expense"), ("KF39", "commission")])
def test_kf38_kf39_a_ratio_moved_by_two_points(rule: str, name: str) -> None:
    assert SETTINGS["expense_ratio_change_limit"] == 0.02
    facts = {
        f"{name}_ratio_12m": Fact(0.10, "ratio"),
        f"{name}_ratio_previous": Fact(0.08, "ratio"),
        f"{name}_ratio_change_size": Fact(0.02, "ratio"),
    }
    (text,) = fired(rule, **facts)
    assert f"The {name} ratio of the last twelve months is 10.0%, against 8.0%" in text
    below = {**facts, f"{name}_ratio_change_size": Fact(0.0199, "ratio")}
    assert fired(rule, **below) == []


def test_kf40_expenses_booked_without_a_line() -> None:
    assert SETTINGS["unallocated_expense_share_limit"] == 0.25
    facts = {
        "unallocated_expense_share": Fact(0.25, "ratio"),
        "unallocated_expenses": Fact(1200.0, "amount"),
        "currency": Fact("TRY", "text"),
    }
    (text,) = fired("KF40", **facts)
    assert text.startswith("25.0% of the expenses of the last twelve months (1,200 TRY)")
    assert "never spread over lines" in text
    assert fired("KF40", **{**facts, "unallocated_expense_share": Fact(0.24, "ratio")}) == []


def test_kf41_unit_costs_stopped_by_a_month_without_expense_rows() -> None:
    facts = {
        "unit_cost_periods_missing": Fact(1.0, "count"),
        "unit_cost_periods": Fact(4.0, "count"),
    }
    (text,) = fired("KF41", **facts)
    assert text.startswith("The unit costs of 1 of 4 periods are not computed")
    assert fired("KF41", **{**facts, "unit_cost_periods_missing": Fact(0.0, "count")}) == []


def test_the_new_rules_are_fixed_rules_with_both_languages_and_follow_the_old_ones() -> None:
    assert set(NEW) <= set(RULES)
    priorities = [RULES[r].priority for r in NEW]
    # the rules before them (KF44 to KF46 of M08 came later, F2a, and follow these)
    assert priorities == sorted(priorities) and min(priorities) > max(
        r.priority for r in RULES.values() if r.id not in NEW and int(r.id[2:]) < 35
    )
    for rule in NEW:
        assert RULES[rule].template_tr and RULES[rule].title_tr and RULES[rule].scope == "run"
        assert RULES[rule].evidence.section in ("recoveries", "expenses")


# --- wiring: the shared run of the tiny baseline -----------------------------------------------


def test_a_run_writes_the_tables_of_both_modules_and_lists_them(default_run) -> None:
    manifest = json.loads(default_run.manifest.read_text(encoding="utf-8"))
    files = {o["name"] for o in manifest["outputs"]}
    wanted = {
        "recoveries.csv",
        "recovery_development.csv",
        "recovery_reconciliation.csv",
        "expenses_by_period.csv",
    }
    assert wanted <= files
    for name in wanted:
        assert (default_run.folder / name).is_file()
    specs = {s["id"] for s in manifest["specs"]}
    assert {"M07", "M09", "RC03", "RC04", "EX04", "EX05"} <= specs
    assert "M10" not in specs  # M08 is built (F2a) and listed although the baseline skips it


def test_a_run_has_both_pages_and_their_navigation_entries(default_run) -> None:
    pages = {p["module"]: p for p in default_run.report_data["pages"]}
    assert pages["M07"]["anchor"] == "recoveries" and pages["M09"]["anchor"] == "expenses"
    # the committed fixture has no recoveries file in its folder: the flows are derived
    assert pages["M07"]["body"]["source"] == "derived from the to-date fields of claim valuations"
    assert pages["M09"]["body"]["unit_costs"]
    page = default_run.report.read_text(encoding="utf-8")
    assert '<a href="#recoveries">M07 Recoveries</a>' in page
    assert '<a href="#expenses">M09 Expenses</a>' in page
    assert '<section id="recoveries" class="page">' in page
    assert "Expenses booked without a line" in page
    m05 = pages["M05"]["body"]["expenses"]
    assert [e["measure"].split()[0] for e in m05] == ["EX01", "EX02", "EX03"]  # M05 as it was
