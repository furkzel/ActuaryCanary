"""The terminal confirmation for a sheet of one of the four feeds built by F1bc: the proposal is
shown with the fields of its concept, a column is mapped by hand, and a sheet that looks like
two concepts is given its concept by the user (records 0028, 0381)."""

from datetime import date

from rich.console import Console

from actuarycanary.cli.confirm import confirm_tables
from actuarycanary.recognition.tables import recognise_table
from actuarycanary.ui.scan import reason_not_recognised
from tests.recognition.build import DICTIONARY, table

N = 6


def _recoveries(types: list[str], **renamed: str) -> dict[str, list]:
    columns: dict[str, list] = {
        "İŞLEM NO": [f"R{k}" for k in range(N)],
        "HASAR NO": [f"C{k}" for k in range(N)],
        "KAYIT TARİHİ": [date(2024, 1 + k, 28) for k in range(N)],
        "TUTAR": [100.0 + k for k in range(N)],
        "DÖVİZ": ["TRY"] * N,
        "TÜR": [types[k % len(types)] for k in range(N)],
    }
    return {renamed.get(k, k): v for k, v in columns.items()}


def _ask(monkeypatch, *answers: str) -> None:  # noqa: ANN001
    replies = iter(answers)
    monkeypatch.setattr(
        "actuarycanary.cli.confirm.Prompt.ask", lambda *args, **kwargs: next(replies)
    )


def test_a_recoveries_sheet_is_proposed_and_a_column_mapped_by_hand(monkeypatch) -> None:  # noqa: ANN001
    raw = table(_recoveries(["RÜCU", "SOVTAJ"], **{"TUTAR": "GELEN"}))
    rec = recognise_table(raw, "tahsilat.xlsx", DICTIONARY)
    assert rec.concept == "recoveries", rec.rejection
    assert "amount" in rec.missing(DICTIONARY)
    column = rec.headers.index("GELEN") + 1
    _ask(monkeypatch, "e", f"{column}=amount", "")
    console = Console(record=True, width=160)
    (answer,) = confirm_tables(console, [(rec, raw)], DICTIONARY)
    assert answer.concept == "recoveries" and answer.missing(DICTIONARY) == []
    assert next(m for m in answer.mappings if m.source == "GELEN").field == "amount"
    shown = console.export_text()
    assert "Concept: recoveries" in shown
    assert "Fields of recoveries: transaction_id, claim_id, booking_date" in shown


def test_a_sheet_that_was_not_recognised_gets_its_concept_from_the_user(monkeypatch) -> None:  # noqa: ANN001
    raw = table(_recoveries(["K1", "K2", "K3"]))  # the company's own type codes
    rec = recognise_table(raw, "export.xlsx", DICTIONARY)
    assert rec.concept is None
    reason = reason_not_recognised(rec)
    assert reason == rec.rejection and reason.startswith("best guess ")
    assert "rejected: margin" in reason and "threshold" not in reason
    _ask(monkeypatch, "e", "concept=reinsurance_transactions", "concept=recoveries", "")
    console = Console(record=True, width=160)
    (answer,) = confirm_tables(console, [(rec, raw)], DICTIONARY)
    assert answer.concept == "recoveries" and answer.missing(DICTIONARY) == []
    assert "Fields of reinsurance_transactions: transaction_id, treaty_id" in console.export_text()
