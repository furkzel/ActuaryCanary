"""M09 Expenses: the module on expenses alone and with the optional feeds, its table at the
level the expenses were booked, and the skip reason of its specification."""

from datetime import date

import pytest

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.modules.expenses import AT_VALUE_DATE, NOMINAL, expense_table
from actuarycanary.modules.runner import ModuleState, run_modules
from actuarycanary.modules.views import MODULE_VIEWS, views_of
from actuarycanary.quality.engine import evaluate
from actuarycanary.structures.periods import Period
from tests.measures.helpers import CATALOGUE, make_inputs
from tests.quality.builders import claim, cv, expense, policy, premium

M09 = CATALOGUE.modules["M09"]
CUT_OFF = date(2024, 3, 31)
VALUATIONS = [cv(1), cv(2, paid_to_date=40.0), cv(3, paid_to_date=100.0)]
EXPENSES = [
    expense(type="ADMINISTRATION", amount=30.0, period=date(2024, m, 28), segment="LIFE", line="X")
    for m in (1, 2, 3)
] + [
    expense(type="ADMINISTRATION", amount=50.0, period=date(2024, 3, 31)),  # not allocated
    expense(type="ACQUISITION", amount=20.0, period=date(2024, 3, 31), segment="LIFE"),
    expense(type="CLAIMS_HANDLING_UNALLOCATED", amount=9.0, period=date(2024, 3, 31)),
]
FULL = {
    "claim_valuations": VALUATIONS,
    "claims": [claim(segment="LIFE", line="X")],
    "policies": [policy(end_date=date(2025, 1, 1))],
    "premiums": [
        premium(amount=1200.0),
        premium(transaction_id="T2", type="COMMISSION", amount=120.0),
    ],
    "expenses": EXPENSES,
}


def _run(rows: dict, **extra):
    inputs = make_inputs(rows, cut_off=CUT_OFF, **extra)
    feeds = {
        c: CanonicalFeed(c, "1", f, tuple(x for x in f.columns if not x.startswith("_")), ())
        for c, f in inputs.feeds.items()
    }
    quality = evaluate(CATALOGUE, feeds, dict(inputs.feeds), cut_off=CUT_OFF)
    analysis = run_modules(
        CATALOGUE, inputs, quality, Period.YEAR, ReinsuranceBasis.GROSS, ValueBasis.NOMINAL
    )
    return analysis, inputs


def test_the_specification_lists_the_five_measures_and_needs_expenses_only() -> None:
    assert M09.measures == ["EX01", "EX02", "EX03", "EX04", "EX05"] and M09.methods == []
    assert M09.required_all == ["expenses"] and M09.implemented and M09.status == "draft"


def test_with_every_feed_the_five_measures_are_computed() -> None:
    analysis, _ = _run(FULL)
    outcome = analysis.get("M09")
    assert outcome.state in (ModuleState.RAN, ModuleState.LIMITED)
    assert {m.measure for m in outcome.available} == {"EX01", "EX02", "EX03", "EX04", "EX05"}


def test_the_module_asks_deeper_views_than_m05_and_leaves_m05_as_it_was() -> None:
    analysis, _ = _run(FULL)
    m05 = [
        (m.measure, m.request.breakdowns, m.request.period) for m in analysis.get("M05").measures
    ]
    for measure in ("EX01", "EX02", "EX03"):
        assert [v for v in m05 if v[0] == measure] == [(measure, ("calendar_period",), Period.YEAR)]
    m09 = [
        (m.measure, m.request.breakdowns, m.request.period) for m in analysis.get("M09").measures
    ]
    assert ("EX02", ("segment", "line", "calendar_period"), Period.MONTH) in m09
    assert ("EX01", ("calendar_period",), Period.MONTH) in m09
    assert ("EX04", ("segment", "line", "calendar_period"), Period.YEAR) in m09
    assert set(MODULE_VIEWS) == {"M09"}
    assert [v.breakdowns for v in views_of("M05", "EX02")] == [("calendar_period",)]
    # the yearly view is computed once and shared by both modules
    shared = [
        r for r in analysis.results() if r.measure == "EX02" and r.request.period is Period.YEAR
    ]
    assert len(shared) == 1


def test_on_expenses_alone_the_module_runs_and_each_measure_says_what_it_lacks() -> None:
    analysis, _ = _run({"claim_valuations": VALUATIONS, "expenses": EXPENSES})
    outcome = analysis.get("M09")
    assert outcome.state is ModuleState.LIMITED
    assert {m.measure for m in outcome.available} == {"EX03", "EX05"}
    reasons = " | ".join(outcome.reasons)
    assert "EX01, EX02: premiums is not loaded; policies is not loaded" in reasons
    assert "EX04: policies is not loaded" in reasons


def test_without_expenses_the_module_is_skipped_in_the_words_of_its_specification() -> None:
    analysis, _ = _run({"claim_valuations": VALUATIONS})
    outcome = analysis.get("M09")
    assert outcome.state is ModuleState.SKIPPED
    assert outcome.reasons == (M09.skip_reason,)
    assert outcome.reasons[0].startswith(
        "Expenses did not run: no expenses were loaded. Load expenses.xlsx to enable it"
    )


# --- the table of the module ----------------------------------------------------------------


def test_expenses_stay_at_the_level_they_were_booked() -> None:
    _, inputs = _run(FULL)
    table = expense_table(inputs)
    rows = {
        (r["month"], r["type"], r["segment"], r["line"]): r[NOMINAL]
        for r in table.frame.iter_rows(named=True)
    }
    march = date(2024, 3, 31)
    assert rows[(march, "ADMINISTRATION", "LIFE", "X")] == 30.0
    assert rows[(march, "ADMINISTRATION", None, None)] == 50.0  # booked without a line: stays so
    assert rows[(march, "ACQUISITION", "LIFE", None)] == 20.0  # a segment, no line
    assert rows[(date(2024, 1, 31), "ADMINISTRATION", "LIFE", "X")] == 30.0
    # nothing was spread: the amounts with a line are the amounts booked with a line
    with_line = table.frame.filter(table.frame["line"].is_not_null())[NOMINAL].sum()
    assert with_line == 90.0 and table.frame[NOMINAL].sum() == 169.0
    assert table.unallocated[NOMINAL].sum() == 79.0


def test_the_table_has_no_value_date_prices_without_a_price_index_and_says_so() -> None:
    _, inputs = _run(FULL)
    table = expense_table(inputs)
    assert table.frame[AT_VALUE_DATE].null_count() == table.frame.height
    assert any(n.startswith("no amounts at value-date prices:") for n in table.notes)


def test_the_table_at_value_date_prices() -> None:
    market = [
        ("CPI_TR", "PRICE_INDEX", date(2024, 1, 31), 100.0),
        ("CPI_TR", "PRICE_INDEX", date(2024, 2, 29), 110.0),
        ("CPI_TR", "PRICE_INDEX", date(2024, 3, 31), 121.0),
    ]
    _, inputs = _run(FULL, market_rows=market)
    table = expense_table(inputs)
    january = table.frame.filter(table.frame["month"] == date(2024, 1, 31))
    assert january[NOMINAL].item() == 30.0
    assert january[AT_VALUE_DATE].item() == pytest.approx(36.3)  # 30 x 121 / 100
    march = table.frame.filter(table.frame["month"] == date(2024, 3, 31))
    assert march[AT_VALUE_DATE].to_list() == march[NOMINAL].to_list()
