"""The four feeds built by F1bc (reinsurance_treaties, reinsurance_transactions, recoveries,
ledger): typed reading by the field types of their specifications (CV07) and the row rules the
canonical step applies (DV-RTY-01, -02, -03, -08; DV-RTR-01 to -04; DV-RCV-01 to -04;
DV-LDG-01, -02, -04, -05), each with rows that pass and rows that fail."""

from datetime import date
from typing import Any

import polars as pl
import pytest

from actuarycanary.canonical.feeds import UNKNOWN, UNMAPPED, CanonicalFeed, canonicalise
from actuarycanary.spec.loader import load_specs
from tests.canonical.test_feeds import _rules, _table

SPECS = load_specs()


def feed(concept: str, rows: list[dict[str, Any]]) -> CanonicalFeed:
    return canonicalise(_table(rows, concept), SPECS.data[concept])


def treaty(**values: Any) -> dict[str, Any]:
    row = {
        "treaty_id": "QS_MOTOR",
        "treaty_type": "QUOTA_SHARE",
        "inception_date": date(2024, 1, 1),
        "expiry_date": date(2025, 1, 1),
        "line": "MOTOR_OD",
        "currency": "TRY",
        "cession_share": 0.3,
    }
    return row | values


def movement(**values: Any) -> dict[str, Any]:
    row = {
        "transaction_id": "T1",
        "treaty_id": "QS_MOTOR",
        "booking_date": date(2024, 3, 31),
        "amount": 100.0,
        "currency": "TRY",
        "type": "CEDED_PREMIUM",
    }
    return row | values


def recovery(**values: Any) -> dict[str, Any]:
    row = {
        "transaction_id": "R1",
        "claim_id": "C1",
        "booking_date": date(2024, 3, 31),
        "amount": 50.0,
        "currency": "TRY",
        "type": "RECOVERY_SUBROGATION",
    }
    return row | values


def balance(**values: Any) -> dict[str, Any]:
    row = {
        "entity": "ENT_A",
        "account": "600.01",
        "period": date(2024, 3, 31),
        "closing_balance": -1000.0,
        "currency": "TRY",
    }
    return row | values


def test_reinsurance_treaties_take_the_types_of_the_specification() -> None:
    text = {"inception_date": "01.01.2024", "expiry_date": "2025-01-01"}
    read = feed(
        "reinsurance_treaties",
        [
            treaty(treaty_id=17, cession_share="0.25", **text),
            treaty(treaty_id=18, cession_share="a third", **text),
        ],
    )
    frame = read.frame
    assert frame["treaty_id"].to_list() == ["17", "18"]  # a number code stays a code
    assert frame.schema["inception_date"] == pl.Date and frame.schema["cession_share"] == pl.Float64
    assert frame["inception_date"][0] == date(2024, 1, 1)
    assert frame["expiry_date"][0] == date(2025, 1, 1)
    assert frame["cession_share"].to_list() == [0.25, None]
    assert _rules(read) == {"CV07": 1}


def test_reinsurance_transactions_take_the_types_of_the_specification() -> None:
    read = feed(
        "reinsurance_transactions",
        [
            movement(amount="250", claim_id=1001, effective_date="01.03.2024"),
            movement(transaction_id="T2", amount="7.5", claim_id=1002, effective_date="soon"),
        ],
    )
    assert read.frame["claim_id"].to_list() == ["1001", "1002"]
    assert read.frame.schema["booking_date"] == pl.Date
    assert read.frame["effective_date"].to_list() == [date(2024, 3, 1), None]
    assert read.frame["amount"][0] == 250.0
    assert _rules(read) == {"CV07": 1}


def test_recoveries_take_the_types_of_the_specification() -> None:
    read = feed(
        "recoveries",
        [
            recovery(booking_date="31.03.2024", amount="50", expected_amount="10"),
            recovery(
                transaction_id="R2", booking_date="30.04.2024", amount="60", expected_amount=""
            ),
        ],
    )
    assert read.frame["booking_date"].to_list() == [date(2024, 3, 31), date(2024, 4, 30)]
    assert read.frame["amount"].to_list() == [50.0, 60.0]
    assert read.frame["expected_amount"].to_list() == [10.0, None]
    assert read.frame.schema["transaction_id"] == pl.String
    assert "counterparty_type" not in read.fields  # an optional field that is absent stays absent


def test_ledger_takes_the_types_of_the_specification() -> None:
    read = feed(
        "ledger",
        [
            balance(account="600.01.001", period="2024-03-31", closing_balance="-5", debit="12.5"),
            balance(account="0100", period="2024-04-30", closing_balance="8", debit="x"),
        ],
    )
    assert read.frame["account"].to_list() == ["600.01.001", "0100"]  # dots and zeros survive
    assert read.frame["period"].to_list() == [date(2024, 3, 31), date(2024, 4, 30)]
    assert read.frame["debit"].to_list() == [12.5, None]
    assert read.frame["closing_balance"].to_list() == [-5.0, 8.0]
    assert _rules(read) == {"CV07": 1}


# --- row rules ----------------------------------------------------------------------------


def test_clean_rows_of_every_feed_pass_every_row_rule() -> None:
    clean = {
        "reinsurance_treaties": [
            treaty(),
            treaty(inception_date=date(2025, 1, 1), expiry_date=date(2026, 1, 1)),
        ],
        "reinsurance_transactions": [movement(), movement(transaction_id="T2")],
        "recoveries": [recovery(), recovery(transaction_id="R2")],
        "ledger": [balance(), balance(account="700")],
    }
    for concept, rows in clean.items():
        read = feed(concept, rows)
        assert read.frame.height == 2 and read.findings == (), concept


@pytest.mark.parametrize(
    ("concept", "row", "prefix", "owner"),
    [
        ("recoveries", recovery, "DV-RCV", "claim_id"),
        ("reinsurance_transactions", movement, "DV-RTR", "treaty_id"),
    ],
)
def test_rules_01_to_04_of_the_movement_feeds(concept, row, prefix, owner) -> None:
    read = feed(
        concept,
        [
            row(),
            row(transaction_id=None),  # 01
            row(transaction_id="B", **{owner: None}),  # 01
            row(transaction_id="C", amount=None),  # 01
            row(transaction_id="D", type="SOMETHING"),  # 02
            row(transaction_id="E", currency="lira"),  # 03
            row(transaction_id="F", currency=None),  # 03
            row(transaction_id="G"),
            row(transaction_id="G"),  # 04, identical: kept once
            row(transaction_id="H", amount=1.0),
            row(transaction_id="H", amount=2.0),  # 04, conflicting: the later row is kept
        ],
    )
    assert _rules(read) == {
        f"{prefix}-01": 3,
        f"{prefix}-02": 1,
        f"{prefix}-03": 2,
        f"{prefix}-04": 2,
    }
    frame = read.frame
    assert frame["transaction_id"].to_list() == [row()["transaction_id"], "D", "E", "F", "G", "H"]
    assert frame.filter(pl.col("transaction_id") == "D")["type"].item() == UNMAPPED
    assert (
        frame.filter(pl.col("transaction_id").is_in(["E", "F"]))["currency"].to_list()
        == [UNKNOWN] * 2
    )
    assert frame.filter(pl.col("transaction_id") == "H")["amount"].item() == 2.0
    severities = {f.rule: f.severity for f in read.findings}
    assert severities[f"{prefix}-01"] == "BLOCKING" and severities[f"{prefix}-04"] == "WARNING"


def test_dv_rcv_02_an_unknown_counterparty_becomes_unmapped_and_the_row_stays() -> None:
    read = feed(
        "recoveries",
        [
            recovery(counterparty_type="INSURER"),
            recovery(transaction_id="R2", counterparty_type="?"),
        ],
    )
    assert read.frame["counterparty_type"].to_list() == ["INSURER", UNMAPPED]
    assert _rules(read) == {"DV-RCV-02": 1}


def test_dv_rty_01_and_03_rows_that_cannot_be_placed_are_excluded() -> None:
    read = feed(
        "reinsurance_treaties",
        [
            treaty(),
            treaty(treaty_id=None),  # 01
            treaty(treaty_id="B", currency=None),  # 01
            treaty(treaty_id="C", expiry_date=date(2024, 1, 1)),  # 03: not after the inception
            treaty(treaty_id="D", expiry_date=date(2023, 6, 1)),  # 03
        ],
    )
    assert read.frame["treaty_id"].to_list() == ["QS_MOTOR"]
    assert _rules(read) == {"DV-RTY-01": 2, "DV-RTY-03": 2}
    assert {f.severity for f in read.findings} == {"BLOCKING"}


def test_dv_rty_02_unknown_labels_become_unmapped() -> None:
    read = feed(
        "reinsurance_treaties",
        [
            treaty(attachment_basis="LOSSES_OCCURRING", loss_basis="RISK"),
            treaty(
                treaty_id="B",
                treaty_type="PARTNERSHIP",
                attachment_basis="RISKS_ATTACHING",
                loss_basis="RISK",
            ),
            treaty(treaty_id="C", attachment_basis="LOSSES_OCCURRING", loss_basis="PER POLICY"),
        ],
    )
    assert read.frame["treaty_type"].to_list() == ["QUOTA_SHARE", UNMAPPED, "QUOTA_SHARE"]
    assert read.frame["loss_basis"].to_list() == ["RISK", "RISK", UNMAPPED]
    assert _rules(read) == {"DV-RTY-02": 2}


def test_dv_rty_08_one_row_per_treaty_inception_and_line() -> None:
    read = feed(
        "reinsurance_treaties",
        [
            treaty(),
            treaty(),  # identical: kept once
            treaty(line="PROPERTY"),  # another line of the same treaty: its own row
            treaty(treaty_id="B", cession_share=0.2),
            treaty(treaty_id="B", cession_share=0.4),  # conflicting: both excluded
        ],
    )
    assert read.frame.select("treaty_id", "line").rows() == [
        ("QS_MOTOR", "MOTOR_OD"),
        ("QS_MOTOR", "PROPERTY"),
    ]
    assert _rules(read) == {"DV-RTY-08": 3}


def test_the_terms_of_a_treaty_are_left_to_the_quality_report() -> None:
    """DV-RTY-05 to -07 list a row and keep it, so that a movement still finds its treaty."""
    read = feed(
        "reinsurance_treaties",
        [treaty(cession_share=None), treaty(treaty_id="B", cession_share=1.5)],
    )
    assert read.frame.height == 2 and read.findings == ()


def test_dv_ldg_01_02_04_05() -> None:
    read = feed(
        "ledger",
        [
            balance(),
            balance(account=None),  # 01
            balance(account="200", closing_balance=None),  # 01
            balance(account="300", period=date(2024, 3, 15)),  # 02: assigned to the month end
            balance(account="400", account_class="PREMIUM"),
            balance(account="500", account_class="MISC"),  # 04
            balance(account="600"),
            balance(account="600"),  # 05, identical: kept once
            balance(account="700", closing_balance=1.0),
            balance(account="700", closing_balance=2.0),  # 05, conflicting: both excluded
        ],
    )
    assert _rules(read) == {"DV-LDG-01": 2, "DV-LDG-02": 1, "DV-LDG-04": 1, "DV-LDG-05": 3}
    frame = read.frame
    assert frame["account"].to_list() == ["600.01", "300", "400", "500", "600"]
    assert frame.filter(pl.col("account") == "300")["period"].item() == date(2024, 3, 31)
    assert frame.filter(pl.col("account") == "500")["account_class"].item() == UNMAPPED
    severities = {f.rule: f.severity for f in read.findings}
    assert severities == {
        "DV-LDG-01": "BLOCKING",
        "DV-LDG-02": "INFO",
        "DV-LDG-04": "WARNING",
        "DV-LDG-05": "WARNING",
    }


def test_at_most_twenty_source_rows_are_listed_and_the_count_is_complete() -> None:
    rows = [recovery(transaction_id=f"R{k}", amount=None) for k in range(30)]
    (found,) = feed("recoveries", [recovery(), *rows]).findings
    assert found.count == 30 and len(found.rows) == 20 and found.rows[0] == 3
