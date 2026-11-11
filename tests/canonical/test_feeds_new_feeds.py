"""Typed reading of the four feeds built by F1bc: reinsurance_treaties, reinsurance_transactions,
recoveries and ledger take the field types of their specifications (CV07)."""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.canonical.feeds import CanonicalFeed, canonicalise
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
    assert _rules(read)["CV07"] == 1


def test_reinsurance_transactions_take_the_types_of_the_specification() -> None:
    read = feed(
        "reinsurance_transactions",
        [
            movement(amount="250", claim_id=1001),
            movement(transaction_id="T2", amount="n/a", claim_id=1002),
        ],
    )
    assert read.frame["amount"].to_list() == [250.0, None]
    assert read.frame["claim_id"].to_list() == ["1001", "1002"]
    assert read.frame.schema["booking_date"] == pl.Date
    assert _rules(read)["CV07"] == 1


def test_recoveries_take_the_types_of_the_specification() -> None:
    read = feed(
        "recoveries",
        [
            recovery(booking_date="31.03.2024", amount="50", expected_amount="10"),
            recovery(
                transaction_id="R2", booking_date="30.04.2024", amount=" ", expected_amount=""
            ),
        ],
    )
    assert read.frame["booking_date"].to_list() == [date(2024, 3, 31), date(2024, 4, 30)]
    assert read.frame["amount"].to_list() == [50.0, None]
    assert read.frame["expected_amount"].to_list() == [10.0, None]
    assert read.frame.schema["transaction_id"] == pl.String
    assert "counterparty_type" not in read.fields  # an optional field that is absent stays absent


def test_ledger_takes_the_types_of_the_specification() -> None:
    read = feed(
        "ledger",
        [
            balance(account="600.01.001", period="2024-03-31", closing_balance="-5", debit="12.5"),
            balance(account="0100", period="2024-04-30", closing_balance="x", debit="0"),
        ],
    )
    assert read.frame["account"].to_list() == ["600.01.001", "0100"]  # dots and zeros survive
    assert read.frame["period"].to_list() == [date(2024, 3, 31), date(2024, 4, 30)]
    assert read.frame["debit"].to_list() == [12.5, 0.0]
    assert read.frame["closing_balance"].to_list() == [-5.0, None]
    assert _rules(read)["CV07"] == 1
