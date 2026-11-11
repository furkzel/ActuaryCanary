"""Recognition of reinsurance treaties, reinsurance transactions, recoveries and the ledger next
to the feeds of version 1.0 (record 0381): the labels of another concept speak against a concept,
a rival that explains only part of what the best concept explains is no rival, and the rule of
record 0375 holds as it was."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.pipeline import recognise_folder
from actuarycanary.recognition.columns import CLASS_SHARE, ColumnMapping, Layer
from actuarycanary.recognition.concepts import (
    MIN_EXPLAINED_SHARE,
    ConceptScore,
    _contradicted,
    judge,
    score_concepts,
)
from actuarycanary.recognition.mapping_profiles import save_profile
from actuarycanary.recognition.tables import (
    Source,
    canonical_table,
    recognise_table,
    to_profile,
    with_field,
)
from actuarycanary.recognition.value_profile import profile_values
from tests.recognition.build import DICTIONARY, SPECS, table

OLD = {"claim_valuations", "claims", "policies", "premiums", "expenses", "market", "interest_rates"}
NEW = {"reinsurance_treaties", "reinsurance_transactions", "recoveries", "ledger"}
LIFE = {"life_in_force", "life_events", "fund_flows"}
N = 12


def _movements(types: list[str], **ids: str) -> dict[str, list]:
    """A movement table: id, date, amount, currency and type, plus the id columns named."""
    columns: dict[str, list] = {
        "transaction_id": [f"T{k:03d}" for k in range(N)],
        "booking_date": [date(2024, 1 + k % 12, 28) for k in range(N)],
        "amount": [100.0 + k for k in range(N)],
        "currency": ["TRY"] * N,
        "type": [types[k % len(types)] for k in range(N)],
    }
    for name, prefix in ids.items():
        columns[name] = [f"{prefix}{k:03d}" for k in range(N)]
    return columns


def _scores(columns: dict[str, list]) -> dict[str, ConceptScore]:
    raw = table(columns)
    profiles = {h: profile_values(raw.frame[h]) for h in raw.headers}
    scores = score_concepts(raw.frame, raw.headers, ("export", "Sheet1"), DICTIONARY, profiles)
    return {s.concept: s for s in scores}


# --- labels of another concept are evidence against a concept -----------------------------


def test_recovery_labels_speak_against_reinsurance_transactions_and_premiums() -> None:
    labels = ["RECOVERY_SUBROGATION", "RECOVERY_SALVAGE"]
    scores = _scores(_movements(labels, claim_id="C"))
    assert scores["recoveries"].contradicted == ()
    assert scores["reinsurance_transactions"].contradicted == ("type",)
    assert scores["premiums"].contradicted == ("type",)
    assert "type" not in scores["reinsurance_transactions"].explains
    # the type no longer counts as found: transaction_id, booking_date, amount, currency remain
    assert scores["reinsurance_transactions"].required == (4, 6)


def test_a_minimal_recoveries_table_is_recognised_by_its_labels() -> None:
    labels = ["RECOVERY_SUBROGATION", "RECOVERY_SALVAGE"]
    rec = recognise_table(table(_movements(labels, claim_id="C")), "export.xlsx", DICTIONARY)
    assert rec.concept == "recoveries", rec.rejection


def test_labels_nobody_recognises_are_no_evidence_either_way() -> None:
    scores = _scores(_movements(["K1", "K2", "K3"], claim_id="C"))
    assert all(s.contradicted == () for s in scores.values())


def test_a_table_that_looks_like_two_concepts_is_taken_for_neither() -> None:
    """Movements on claims with the company's own type codes: recoveries or claim-level ceded
    movements, the columns cannot tell."""
    rec = recognise_table(
        table(_movements(["K1", "K2", "K3"], claim_id="C")), "export.xlsx", DICTIONARY
    )
    assert rec.concept is None
    assert rec.rejection.startswith("best guess recoveries ")
    assert "margin" in rec.rejection
    assert all(not m.used for m in rec.mappings)


def test_the_class_share_boundary_of_a_contradiction() -> None:
    assert CLASS_SHARE == 0.5
    # at the share another concept needs, and just under the share this concept needs
    assert _contradicted({"a": {"type": 0.49}, "b": {"type": 0.5}})["a"] == ("type",)
    assert _contradicted({"a": {"type": 0.5}, "b": {"type": 1.0}})["a"] == ()  # recognised enough
    assert _contradicted({"a": {"type": 0.0}, "b": {"type": 0.49}})["a"] == ()  # nobody's labels
    assert _contradicted({"a": {"type": 0.0}, "b": {"kind": 1.0}})["a"] == ()  # another column


# --- a rival that explains only part of what the best concept explains ---------------------


def _mapped(total: int, explained: tuple[int, ...]) -> tuple[ColumnMapping, ...]:
    return tuple(
        ColumnMapping(f"c{i}", f"f{i}", Layer.CANONICAL, 1.0, "")
        if i in explained
        else ColumnMapping(f"c{i}", None, Layer.NONE, 0.0, "")
        for i in range(total)
    )


def _judged(best_columns: int, rival: tuple[int, ...], total: int = 12, margin: float = 0.05):
    best = ConceptScore(
        "a", 0.95, (6, 6), (0, 0), "", False, _mapped(total, tuple(range(best_columns)))
    )
    other = ConceptScore(
        "b", round(0.95 - margin, 4), (6, 6), (0, 0), "", False, _mapped(total, rival)
    )
    return judge([best, other])


def test_a_rival_explaining_a_strict_subset_is_dominated() -> None:
    verdict = _judged(12, rival=tuple(range(7)))
    assert verdict.accepted is not None and verdict.margin == 0.95


def test_a_rival_explaining_the_same_columns_stays_a_rival() -> None:
    verdict = _judged(12, rival=tuple(range(12)))
    assert verdict.accepted is None and verdict.margin == 0.05


def test_a_rival_explaining_a_column_of_its_own_stays_a_rival() -> None:
    assert _judged(11, rival=(0, 1, 11)).accepted is None


def test_dominance_needs_the_best_concept_to_explain_the_sheet() -> None:
    """Below MIN_EXPLAINED_SHARE every concept stays a rival, so a workbook with a dozen unknown
    columns gains nothing from the rule (record 0375 holds as it was)."""
    assert MIN_EXPLAINED_SHARE == 0.75
    assert _judged(9, rival=(0, 1, 2)).accepted is not None  # 9 of 12 = 75 %
    assert _judged(8, rival=(0, 1, 2)).accepted is None  # 8 of 12 = 67 %
    assert _judged(8, rival=(0, 1, 2), margin=0.6).accepted is not None  # the clear margin


def test_a_reinsurance_transactions_table_is_not_taken_for_premiums() -> None:
    labels = ["CEDED_PREMIUM", "CEDED_CLAIM_PAID", "CEDED_CASE_RESERVE", "RI_COMMISSION"]
    columns = _movements(labels, treaty_id="QS", claim_id="C", policy_id="P")
    scores = _scores(columns)
    assert scores["premiums"].complete  # every required field of premiums is there
    assert scores["premiums"].explains < scores["reinsurance_transactions"].explains
    rec = recognise_table(table(columns), "export.xlsx", DICTIONARY)
    assert rec.concept == "reinsurance_transactions", rec.rejection


def test_a_premiums_table_is_not_taken_for_a_movement_feed() -> None:
    columns = _movements(["WRITTEN", "CANCELLATION"], policy_id="P")
    rec = recognise_table(table(columns), "export.xlsx", DICTIONARY)
    assert rec.concept == "premiums", rec.rejection


def test_expenses_are_not_taken_for_a_ledger_and_a_ledger_not_for_expenses() -> None:
    months = [date(2024, 1 + k % 12, 28) for k in range(N)]
    expenses = {
        "period": months,
        "amount": [10.0 + k for k in range(N)],
        "currency": ["TRY"] * N,
        "type": ["ADMINISTRATION", "ACQUISITION", "CLAIMS_HANDLING"] * 4,
        "line": ["MOTOR_OD"] * N,
        "entity": ["ENT_A"] * N,
    }
    ledger = {
        "entity": ["ENT_A"] * N,
        "account": [f"6{k:02d}.01" for k in range(N)],
        "period": months,
        "closing_balance": [-(1000.0 + k) for k in range(N)],
        "currency": ["TRY"] * N,
    }
    assert recognise_table(table(expenses), "export.xlsx", DICTIONARY).concept == "expenses"
    assert recognise_table(table(ledger), "export.xlsx", DICTIONARY).concept == "ledger"


# --- every sheet of the tiny scenarios ------------------------------------------------------


def _found(sheets: list) -> dict[str, set[str | None]]:
    found: dict[str, set[str | None]] = {}
    for item in sheets:
        found.setdefault(Path(item.workbook.name).stem, set()).add(item.recognition.concept)
    return found


SCENARIOS = ["baseline", "messy_headers", "messy_incremental", "life_book", "reinsurance_heavy"]


@pytest.fixture(scope="module", params=SCENARIOS)
def scenario_sheets(request, recognised_scenario) -> tuple[str, list]:
    return request.param, recognised_scenario(request.param)


def test_every_sheet_of_a_scenario_is_read_as_its_concept(scenario_sheets) -> None:
    scenario, sheets = scenario_sheets
    found = _found(sheets)
    assert set(found) >= OLD | NEW
    for concept in OLD | NEW:
        assert found[concept] == {concept}, (scenario, concept)
    for concept in LIFE & set(found):
        assert found[concept] == {None}, (scenario, concept)
    life = [i.recognition for i in sheets if Path(i.workbook.name).stem in LIFE]
    assert all(r.rejection.startswith("best guess ") and "rejected:" in r.rejection for r in life)
    if scenario in ("life_book", "messy_headers", "messy_incremental"):
        assert set(found) >= LIFE


# --- a mapping edited on the confirmation screen, saved and used again ----------------------


def test_a_ledger_mapping_is_edited_saved_and_used_again(scenario_folder, tmp_path) -> None:
    """The messy ledger writes its credit column as CERDIT. The proposal leaves it out; the user
    maps it, the profile is saved, and the next reading takes the profile and gives the canonical
    data of the generator."""
    folder, profiles = scenario_folder("messy_headers"), tmp_path / "profiles"
    first = recognise_folder(folder, DICTIONARY, None, profiles)
    item = next(i for i in first if i.recognition.concept == "ledger")
    rec = item.recognition
    assert rec.source is Source.AUTOMATIC
    assert next(m for m in rec.mappings if m.source == "CERDIT").field is None

    edited = with_field(rec, "CERDIT", "credit", DICTIONARY)
    save_profile(profiles, to_profile(edited, date(2026, 11, 11)))

    again = recognise_folder(folder, DICTIONARY, None, profiles)
    saved = next(i for i in again if i.recognition.concept == "ledger")
    assert saved.recognition.source is Source.SAVED
    assert next(m for m in saved.recognition.mappings if m.source == "CERDIT").field == "credit"
    others = [i.recognition.source for i in again if i.recognition.concept != "ledger"]
    assert Source.SAVED not in others  # a profile belongs to one layout

    raw, _ = canonical_table(saved.table, saved.recognition, DICTIONARY)
    got = canonicalise(raw, SPECS.data["ledger"]).frame.drop(SOURCE_COLUMNS)
    expected = pl.read_parquet(folder / "canonical" / "ledger.parquet")
    keys = ["entity", "account", "period"]
    assert got.select(expected.columns).sort(keys).equals(expected.sort(keys))
