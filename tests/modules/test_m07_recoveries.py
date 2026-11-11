"""M07 Recoveries: the module on derived flows and on transactions, its tables, and the skip
reason of its specification when no recovery data is loaded."""

from datetime import date

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.canonical.recoveries import build_recoveries, cumulative_at
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.modules.recoveries import (
    NOT_RECONCILED_DERIVED,
    NOT_RECONCILED_NO_FIELDS,
    recovery_tables,
)
from actuarycanary.modules.runner import ModuleState, run_modules
from actuarycanary.quality.engine import evaluate
from actuarycanary.structures.periods import Period
from tests.measures.helpers import CATALOGUE
from tests.measures.recovery_fixtures import (
    BOOKINGS,
    CUT_OFF,
    SAL,
    SUB,
    VALUATIONS,
    book,
    booking,
    valuation,
)

M07 = CATALOGUE.modules["M07"]


def _run(inputs):
    feeds = {
        c: CanonicalFeed(c, "1", f, tuple(x for x in f.columns if not x.startswith("_")), ())
        for c, f in inputs.feeds.items()
    }
    quality = evaluate(CATALOGUE, feeds, dict(inputs.feeds), cut_off=CUT_OFF)
    analysis = run_modules(
        CATALOGUE, inputs, quality, Period.YEAR, ReinsuranceBasis.GROSS, ValueBasis.NOMINAL
    )
    return analysis.get("M07")


def _bare() -> list[dict]:
    return [
        {k: v for k, v in row.items() if not k.endswith("_to_date") or k == "paid_to_date"}
        for row in VALUATIONS
    ]


def test_the_specification_lists_the_four_measures_and_the_triangle_method() -> None:
    assert M07.measures == ["RC01", "RC02", "RC03", "RC04"] and M07.methods == ["MT01"]
    assert M07.implemented and M07.status == "draft"


def test_the_module_runs_on_claim_valuations_alone_with_derived_flows() -> None:
    outcome = _run(book(None))
    assert outcome.state in (ModuleState.RAN, ModuleState.LIMITED)
    assert {m.measure for m in outcome.available} == {"RC01", "RC02", "RC03", "RC04"}
    development = next(m for m in outcome.measures if m.measure == "RC04")
    assert any(n.startswith("source: derived from") for n in development.notes)
    assert outcome.methods_built == ("MT01",) and outcome.methods_missing == ()


def test_the_module_runs_on_transactions() -> None:
    outcome = _run(book(BOOKINGS))
    assert {m.measure for m in outcome.available} == {"RC01", "RC02", "RC03", "RC04"}
    delay = next(m for m in outcome.measures if m.measure == "RC03")
    assert any("recovery transactions (recoveries feed)" in n for n in delay.notes)
    # the default views: delay by type and by line and type, development by type and cell
    views = [m.request.breakdowns for m in outcome.measures if m.measure in ("RC03", "RC04")]
    assert views == [
        ("recovery_type",),
        ("segment", "line", "recovery_type"),
        ("segment", "line", "recovery_type", "origin_period", "development_period"),
    ]


def test_without_recovery_data_the_module_is_skipped_in_the_words_of_its_specification() -> None:
    outcome = _run(book(None, _bare()))
    assert outcome.state is ModuleState.SKIPPED
    assert outcome.reasons == (M07.skip_reason,)
    assert outcome.reasons[0].startswith(
        "Recoveries did not run: no recovery data was loaded. Load recoveries.xlsx, or "
        "claim_valuations.xlsx with subrogation_to_date or salvage_to_date columns"
    )
    assert outcome.measures == ()


def test_with_only_a_subrogation_column_the_salvage_ratio_says_why_it_is_missing() -> None:
    rows = [{k: v for k, v in row.items() if k != "salvage_to_date"} for row in VALUATIONS]
    outcome = _run(book(None, rows))
    assert outcome.state is ModuleState.LIMITED
    assert "RC02: no salvage column in claim_valuations" in outcome.reasons


# --- the tables of the module ---------------------------------------------------------------


def test_flows_per_claim_type_and_month_from_transactions() -> None:
    bookings = [*BOOKINGS, booking(5, "A", date(2022, 6, 20), 2.5, SUB)]
    tables = recovery_tables(book(bookings))
    assert tables.source == "transactions" and tables.available
    rows = tables.flows.select("claim_id", "type", "month", "amount", "bookings", "derived").rows()
    assert rows == [
        ("A", SUB, date(2022, 6, 30), 12.5, 2, False),
        ("A", SAL, date(2023, 3, 31), 20.0, 1, False),
        ("A", SUB, date(2024, 2, 29), 30.0, 1, False),
        ("B", SUB, date(2024, 5, 31), 15.0, 1, False),
    ]


def test_derived_flows_are_flagged_and_there_is_nothing_to_reconcile() -> None:
    tables = recovery_tables(book(None))
    assert tables.source == "derived" and tables.flows["derived"].all()
    assert tables.flows["amount"].sum() == 75.0
    assert tables.reconciliation.height == 0
    assert tables.reconciliation_note == NOT_RECONCILED_DERIVED


def test_the_reconciliation_lists_the_differences_to_the_to_date_fields() -> None:
    agreeing = recovery_tables(book(BOOKINGS))
    assert agreeing.reconciliation.height == 0
    assert "0 of 14 valuations differ" in agreeing.reconciliation_note
    bookings = [*BOOKINGS[:3], booking(4, "B", date(2024, 5, 5), 12.0, SUB)]  # the field says 15
    differing = recovery_tables(book(bookings))
    assert differing.reconciliation.rows() == [("B", SUB, date(2024, 5, 31), 12.0, 15.0, -3.0)]
    assert "1 of 14 valuations differ; the transactions are used" in differing.reconciliation_note


def test_transactions_without_to_date_columns_are_not_reconciled() -> None:
    tables = recovery_tables(book(BOOKINGS, _bare()))
    assert tables.source == "transactions"
    assert tables.reconciliation_note == NOT_RECONCILED_NO_FIELDS


# --- property: a derived recovery never exceeds what was paid on the claim -------------------

steps = st.lists(
    st.tuples(st.floats(0, 1e6, allow_nan=False), st.floats(0, 1), st.floats(0, 1)),
    min_size=1,
    max_size=12,
)


@given(steps)
def test_derived_recoveries_never_exceed_what_was_paid_on_the_claim(drawn) -> None:
    """When the to-date fields never exceed paid_to_date, the flows derived from them, added up
    to any valuation date, never do either: the derivation adds nothing and loses nothing."""
    rows, paid = [], 0.0
    for k, (payment, share_sub, share_sal) in enumerate(drawn):
        paid = round(paid + payment, 2)
        sub = round(paid * share_sub / 2, 2)
        sal = round(paid * share_sal / 2, 2)
        day = date(2023 + k // 12, k % 12 + 1, 28)
        rows.append(valuation("P", day, paid, sub=sub, sal=sal))
    valuations = pl.DataFrame(rows)
    flows = build_recoveries(None, valuations).frame
    booked = cumulative_at(valuations, flows, "booked")
    both = valuations.join(booked, on=["claim_id", "valuation_date"])
    to_date = pl.col("subrogation_to_date") + pl.col("salvage_to_date")
    assert both.filter((pl.col("booked") - to_date).abs() > 0.011).height == 0
    assert both.filter(pl.col("booked") > pl.col("paid_to_date") + 0.011).height == 0
