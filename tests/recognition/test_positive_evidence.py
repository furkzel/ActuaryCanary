"""A concept is accepted only on positive evidence; a workbook that merely resembles one is listed
as not recognised, with the best guess and the reason (record 0375)."""

from datetime import date

import pytest

from actuarycanary.recognition.columns import ColumnMapping, Layer
from actuarycanary.recognition.concepts import (
    CLEAR_MARGIN,
    MIN_EXPLAINED_SHARE,
    MIN_MARGIN,
    MIN_REQUIRED_SHARE,
    ConceptScore,
    judge,
)
from actuarycanary.recognition.tables import recognise_table
from tests.recognition.build import DICTIONARY, table, valuations

ROWS = 12


def _column(name: str, i: int):
    if name.endswith(("_date", "date", "period")) or name == "period":
        return [date(2024, 1 + k % 12, 28) for k in range(ROWS)]
    if name in ("amount", "closing_balance", "opening_balance", "debit", "credit", "rate"):
        return [100.0 + k for k in range(ROWS)]
    if name.endswith("_id") or name == "account":
        return [f"{name[:3].upper()}{k:03d}" for k in range(ROWS)]
    return [f"{name}_{k % 3}" for k in range(ROWS)]


def _sheet(*headers: str):
    return table({h: _column(h, i) for i, h in enumerate(headers)})


# the headers of the planned feeds, as the generator writes them (they sit in phase2/)
PLANNED = {
    "reinsurance_treaties.xlsx": (
        "treaty_id treaty_type attachment_basis loss_basis segment line entity currency "
        "index_series inception_date expiry_date cession_share retention limit number_of_lines "
        "aggregate_deductible aggregate_limit reinstatements reinstatement_rate placed_share "
        "premium_rate ceding_commission"
    ),
    "reinsurance_transactions.xlsx": (
        "transaction_id treaty_id booking_date amount currency type claim_id policy_id "
        "event_code effective_date segment line"
    ),
    "recoveries.xlsx": (
        "transaction_id claim_id booking_date amount currency type counterparty_type"
    ),
    "ledger.xlsx": (
        "entity account period closing_balance opening_balance debit credit currency "
        "account_name account_class segment"
    ),
    "life_in_force.xlsx": (
        "contract_id product line entry_date birth_date sex sum_assured premium status "
        "valuation_date fund_value channel segment currency term_years policy_year age lapse_flag"
    ),
    "life_events.xlsx": "contract_id event_date event_type amount currency status segment",
    "fund_flows.xlsx": "contract_id flow_date flow_type amount currency fund segment",
}


@pytest.mark.parametrize("file", sorted(PLANNED))
def test_a_table_of_a_planned_feed_is_not_taken_for_a_known_concept(file):
    rec = recognise_table(_sheet(*PLANNED[file].split()), file, DICTIONARY)
    assert rec.concept is None, rec.candidates[0].describe()
    assert rec.rejection.startswith("best guess ") and "rejected:" in rec.rejection
    assert all(not m.used for m in rec.mappings)


def test_a_market_like_table_with_extra_columns_is_not_taken_for_market():
    headers = ("date", "series_id", "value", "kind", "tenor", "compounding", "quote", "source")
    rec = recognise_table(_sheet(*headers), "rates.xlsx", DICTIONARY)
    assert rec.concept is None
    assert "columns are explained" in rec.rejection or "margin" in rec.rejection


def test_the_rejection_names_the_best_guess_and_every_reason():
    rec = recognise_table(_sheet(*PLANNED["ledger.xlsx"].split()), "ledger.xlsx", DICTIONARY)
    assert rec.rejection.startswith(f"best guess {rec.candidates[0].concept} ")
    assert "required fields found" in rec.rejection


def test_a_recognised_sheet_has_no_rejection():
    raw = table(
        {"claim_id": ["A", "B"], **{k: v[:2] for k, v in valuations().items() if k != "claim_id"}}
    )
    rec = recognise_table(raw, "claim_valuations.xlsx", DICTIONARY)
    assert rec.concept == "claim_valuations" and rec.rejection == ""


# --- the boundaries, on scores built by hand ------------------------------------------------


def _columns(total, explained, personal=0):
    out = []
    for i in range(total):
        if i < explained:
            out.append(ColumnMapping(f"c{i}", f"f{i}", Layer.CANONICAL, 1.0, ""))
        elif i < explained + personal:
            out.append(ColumnMapping(f"c{i}", None, Layer.PERSONAL, 1.0, "", "name"))
        else:
            out.append(ColumnMapping(f"c{i}", None, Layer.NONE, 0.0, ""))
    return tuple(out)


def _verdict(margin, found=6, total=6, columns=10, explained=10):
    best = ConceptScore(
        "a", 0.95, (found, total), (0, 0), "keys unique", False, _columns(columns, explained)
    )
    nxt = ConceptScore("b", round(0.95 - margin, 4), (0, 6), (0, 0), "", False, ())
    return judge([best, nxt])


def test_the_margin_must_be_above_the_stated_value_not_equal_to_it():
    assert MIN_MARGIN == 0.30
    assert _verdict(0.30).accepted is None
    assert _verdict(0.3001).accepted is not None
    assert any("margin" in r for r in _verdict(0.30).reasons)


def test_extra_columns_matter_only_below_the_clear_margin():
    assert CLEAR_MARGIN == 0.50 and MIN_EXPLAINED_SHARE == 0.75
    assert _verdict(0.49, columns=12, explained=8).accepted is None  # 8 of 12 = 67 %
    assert _verdict(0.49, columns=12, explained=9).accepted is not None  # 9 of 12 = 75 %
    assert _verdict(0.50, columns=40, explained=6).accepted is not None  # clear margin


def test_the_required_share_boundary():
    assert MIN_REQUIRED_SHARE == 0.80
    assert _verdict(0.6, found=4, total=5).accepted is not None  # 80 %
    assert _verdict(0.6, found=3, total=4).accepted is None  # 75 %
    assert any("required fields" in r for r in _verdict(0.6, found=3, total=4).reasons)


def test_personal_data_columns_count_as_explained():
    best = ConceptScore("a", 0.95, (6, 6), (0, 0), "keys unique", False, _columns(8, 6, personal=2))
    nxt = ConceptScore("b", 0.60, (0, 6), (0, 0), "", False, ())
    assert judge([best, nxt]).accepted is best  # margin 0.35, 8 of 8 explained
    bare = ConceptScore("a", 0.95, (6, 6), (0, 0), "keys unique", False, _columns(8, 6))
    assert judge([bare, nxt]).accepted is bare  # 6 of 8 = 75 %
    thin = ConceptScore("a", 0.95, (6, 6), (0, 0), "keys unique", False, _columns(9, 6))
    assert judge([thin, nxt]).accepted is None  # 6 of 9 = 67 %
