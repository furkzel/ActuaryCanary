"""CV09 allocation of treaty-level ceded movements and the CV03 1.1.0 ceded fields.

Spec IDs proved: CV09, CV03.
"""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.allocation import (
    APPROXIMATION,
    BY_CEDED_MOVEMENT,
    BY_EARNED,
    BY_WRITTEN,
    GIVEN,
    NOT_ALLOCATED,
    UNALLOCATED,
    allocate,
    ceded_valuation_fields,
    split_to_cents,
)
from actuarycanary.methods.reinsurance import ClaimBook, Section, apply_programme

YEAR = {"inception": date(2020, 1, 1), "expiry": date(2021, 1, 1), "currency": "TRY"}
QS = Section("QS", "QUOTA_SHARE", cession_share=0.25, lines=frozenset({"OD"}), **YEAR)
XL = Section(
    "XL",
    "EXCESS_OF_LOSS",
    retention=100,
    limit=1000,
    premium_rate=0.1,
    lines=frozenset({"OD"}),
    **YEAR,
)


def _book() -> ClaimBook:
    # claim A pays 300 in March, claim B 100 in March and 200 more in April
    return ClaimBook(
        valuations=pl.DataFrame(
            {
                "claim_id": ["A", "B", "B"],
                "valuation_date": [date(2020, 3, 31), date(2020, 3, 31), date(2020, 4, 30)],
                "paid": [300.0, 100.0, 300.0],
                "incurred": [300.0, 100.0, 300.0],
            }
        ),
        claims=pl.DataFrame(
            {
                "claim_id": ["A", "B"],
                "occurrence_date": [date(2020, 2, 1), date(2019, 12, 1)],  # B before the treaty
                "line": ["OD", "OD"],
                "policy_id": ["P1", "P2"],
            }
        ),
    )


def _moves(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "transaction_id": pl.String,
            "treaty_id": pl.String,
            "booking_date": pl.Date,
            "amount": pl.Float64,
            "type": pl.String,
            "claim_id": pl.String,
            "policy_id": pl.String,
        },
        orient="row",
    )


def _written() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "policy_id": ["P1", "P2", "P3"],
            "booking_date": [date(2020, 3, 5), date(2020, 3, 20), date(2020, 4, 1)],
            "amount": [600.0, 200.0, 1000.0],
            "line": ["OD", "OD", "OD"],
            "start_date": [date(2020, 3, 1), date(2020, 3, 16), date(2020, 4, 1)],
            "end_date": [date(2021, 3, 1), date(2021, 3, 16), date(2021, 4, 1)],
        }
    )


def test_split_to_cents_adds_up_and_puts_the_remainder_on_the_largest() -> None:
    parts = split_to_cents(100.0, np.array([1.0, 1.0, 1.0]))
    assert parts.sum() == pytest.approx(100.0, abs=1e-9)
    assert sorted(parts.tolist()) == [33.33, 33.33, 33.34]


def test_claim_movements_follow_the_computed_ceded_movement() -> None:
    book = _book()  # claim B occurred before the treaty: not in the quota share's scope
    application = apply_programme([QS], book)
    moves = _moves(
        [
            ("1", "QS", date(2020, 3, 31), 80.0, "CEDED_CLAIM_PAID", None, None),  # treaty level
            ("2", "QS", date(2020, 3, 31), 75.0, "CEDED_CLAIM_PAID", "A", None),  # given
            ("3", "QS", date(2020, 6, 30), 10.0, "CEDED_CLAIM_PAID", None, None),  # nothing moved
        ]
    )
    result = allocate(moves, [QS], book, application, None).rows
    given = result.filter(pl.col("transaction_id") == "2")
    assert given["method"].to_list() == [GIVEN] and given["claim_id"].to_list() == ["A"]
    first = result.filter(pl.col("transaction_id") == "1")
    assert first["method"].to_list() == [BY_CEDED_MOVEMENT]
    assert first["claim_id"].to_list() == ["A"] and first["amount"].to_list() == [80.0]
    # June: no claim moved; the fallback spreads it over line and origin cells in scope
    june = result.filter(pl.col("transaction_id") == "3")
    assert june["method"].unique().to_list() == [APPROXIMATION]
    assert june["amount"].sum() == pytest.approx(10.0)
    assert june["origin_year"].to_list() == [2020]
    left = allocate(moves, [QS], book, application, None, fallback=UNALLOCATED).rows
    assert left.filter(pl.col("transaction_id") == "3")["method"].to_list() == [NOT_ALLOCATED]


def test_excess_of_loss_movements_follow_the_change_of_expected_ceded() -> None:
    book = ClaimBook(
        valuations=pl.DataFrame(
            {
                "claim_id": ["A", "B", "B"],
                "valuation_date": [date(2020, 3, 31), date(2020, 3, 31), date(2020, 4, 30)],
                "paid": [400.0, 200.0, 700.0],
                "incurred": [400.0, 200.0, 700.0],
            }
        ),
        claims=pl.DataFrame(
            {
                "claim_id": ["A", "B"],
                "occurrence_date": [date(2020, 2, 1)] * 2,
                "line": ["OD", "OD"],
            }
        ),
    )
    application = apply_programme([XL], book)
    moves = _moves(
        [
            ("1", "XL", date(2020, 3, 31), 100.0, "CEDED_CLAIM_PAID", None, None),
            ("2", "XL", date(2020, 4, 30), 33.0, "CEDED_CLAIM_PAID", None, None),
        ]
    )
    rows = allocate(moves, [XL], book, application, None).rows
    march = dict(
        rows.filter(pl.col("transaction_id") == "1").select("claim_id", "amount").iter_rows()
    )
    assert march == {"A": 75.0, "B": 25.0}  # expected ceded 300 and 100 in March
    april = rows.filter(pl.col("transaction_id") == "2")
    assert april["claim_id"].to_list() == ["B"] and april["amount"].to_list() == [33.0]


def test_premium_goes_to_policies_by_written_or_earned_premium() -> None:
    moves = _moves(
        [
            ("1", "QS", date(2020, 3, 31), 200.0, "CEDED_PREMIUM", None, None),
            ("2", "QS", date(2020, 3, 31), 50.0, "RI_COMMISSION", None, None),
            ("3", "XL", date(2020, 4, 30), 10.0, "CEDED_PREMIUM", None, None),
            ("4", "QS", date(2020, 3, 31), 7.0, "CEDED_PREMIUM", None, "P1"),
        ]
    )
    rows = allocate(moves, [QS, XL], _book(), None, _written()).rows
    proportional = dict(
        rows.filter(pl.col("transaction_id") == "1").select("policy_id", "amount").iter_rows()
    )
    assert proportional == {"P1": 150.0, "P2": 50.0}  # written in March: 600 and 200
    commission = dict(
        rows.filter(pl.col("transaction_id") == "2").select("policy_id", "amount").iter_rows()
    )
    assert commission == {"P1": 37.5, "P2": 12.5}
    assert rows.filter(pl.col("transaction_id") == "1")["method"].unique().to_list() == [BY_WRITTEN]
    earned = rows.filter(pl.col("transaction_id") == "3")
    assert earned["method"].unique().to_list() == [BY_EARNED]
    # April earned: 30/365 of 600, of 200 and of 1000
    weights = np.array([600 * 30 / 365, 200 * 30 / 365, 1000 * 30 / 365])
    expected = dict(zip(["P1", "P2", "P3"], split_to_cents(10.0, weights).tolist(), strict=True))
    assert dict(earned.select("policy_id", "amount").iter_rows()) == expected
    assert rows.filter(pl.col("transaction_id") == "4")["method"].to_list() == [GIVEN]
    totals = rows.group_by("transaction_id").agg(pl.col("amount").sum()).sort("transaction_id")
    assert totals["amount"].to_list() == pytest.approx([200.0, 50.0, 10.0, 7.0], abs=1e-9)


def test_ceded_fields_are_taken_as_given_or_built_from_the_movements() -> None:
    book = _book()
    application = apply_programme([QS], book)
    moves = _moves(
        [
            ("1", "QS", date(2020, 3, 31), 75.0, "CEDED_CLAIM_PAID", "A", None),
            ("2", "QS", date(2020, 3, 31), 20.0, "CEDED_CASE_RESERVE", None, None),
        ]
    )
    allocation = allocate(moves, [QS], book, application, None)
    valuations = book.valuations.rename({"paid": "paid_to_date"}).with_columns(
        case_reserve=pl.lit(0.0)
    )
    given = valuations.with_columns(ceded_paid_to_date=pl.lit(1.0), ceded_reserve=pl.lit(0.0))
    same, changed = ceded_valuation_fields(given, allocation)
    assert not changed and same.equals(given)  # CV03 1.1.0: no value moves when fields exist
    filled, changed = ceded_valuation_fields(valuations, allocation)
    assert changed
    a = filled.filter(pl.col("claim_id") == "A").row(0, named=True)
    # the reserve change of March had no claim moving: aggregate fallback, so it stays a cell
    assert a["ceded_paid_to_date"] == 75.0 and a["ceded_source"] == "given"
    assert filled.filter(pl.col("claim_id") == "B")["ceded_paid_to_date"].to_list() == [0.0, 0.0]
