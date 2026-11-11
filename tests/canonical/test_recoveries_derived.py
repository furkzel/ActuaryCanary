"""Recovery flows in one structure (recoveries spec, decision 0203): derived from the to-date
fields of claim valuations when no recoveries feed is loaded; the transactions win when both
exist and the differences are listed (DV-RCV-08)."""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.canonical.feeds import UNKNOWN
from actuarycanary.canonical.recoveries import (
    DERIVED,
    DERIVED_RULE,
    NONE,
    OTHER,
    SALVAGE,
    SUBROGATION,
    TRANSACTIONS,
    build_recoveries,
    derive_recoveries,
    recovery_differences,
)
from actuarycanary.io.excel import SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET

JAN, FEB, MAR, APR = (date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30))


def _valuations(rows: list[tuple[Any, ...]], columns: tuple[str, ...]) -> pl.DataFrame:
    names = ("claim_id", "valuation_date", "currency", *columns)
    frame = pl.DataFrame(rows, schema=list(names), orient="row")
    return frame.with_columns(
        pl.lit("claim_valuations.xlsx").alias(SOURCE_FILE),
        pl.lit("v").alias(SOURCE_SHEET),
        (pl.int_range(pl.len()) + 2).cast(pl.Int64).alias(SOURCE_ROW),
    )


# claim A: subrogation 0, 40, 40, 30 (a reversal of 10 in April); salvage 0, 0, 25, 25
# claim B: subrogation starts at 15 on its first valuation; salvage empty, then 5
HAND = _valuations(
    [
        ("A", JAN, "TRY", 0.0, 0.0),
        ("A", FEB, "TRY", 40.0, 0.0),
        ("A", MAR, "TRY", 40.0, 25.0),
        ("A", APR, "TRY", 30.0, 25.0),
        ("B", FEB, "USD", 15.0, None),
        ("B", MAR, "USD", 15.0, 5.0),
    ],
    ("subrogation_to_date", "salvage_to_date"),
)


def _feed(rows: list[tuple[str, str, date, float, str, str]]) -> pl.DataFrame:
    names = ["transaction_id", "claim_id", "booking_date", "amount", "currency", "type"]
    return pl.DataFrame(rows, schema=names, orient="row").with_columns(
        pl.lit("recoveries.xlsx").alias(SOURCE_FILE),
        pl.lit("r").alias(SOURCE_SHEET),
        (pl.int_range(pl.len()) + 2).cast(pl.Int64).alias(SOURCE_ROW),
    )


def test_flows_are_the_increments_between_consecutive_valuations() -> None:
    flows = derive_recoveries(HAND)
    got = flows.select("claim_id", "booking_date", "type", "amount", "currency").rows()
    assert got == [
        ("A", FEB, SUBROGATION, 40.0, "TRY"),
        ("A", MAR, SALVAGE, 25.0, "TRY"),
        ("A", APR, SUBROGATION, -10.0, "TRY"),  # a negative increment is a reversal and is kept
        ("B", FEB, SUBROGATION, 15.0, "USD"),  # the first valuation counts from zero
        ("B", MAR, SALVAGE, 5.0, "USD"),
    ]
    assert flows["transaction_id"].to_list()[0] == "DERIVED-A-202402-SUB"
    assert flows["transaction_id"].n_unique() == flows.height
    assert flows[SOURCE_ROW].to_list() == [3, 4, 5, 6, 7]  # the row of the later valuation


def test_derived_flows_add_up_to_the_to_date_fields() -> None:
    flows = derive_recoveries(HAND)
    assert recovery_differences(flows, HAND).height == 0
    totals = dict(flows.group_by("claim_id").agg(pl.col("amount").sum()).iter_rows())
    assert totals == {"A": 55.0, "B": 20.0}


def test_without_a_feed_the_flows_are_derived_and_say_so() -> None:
    built = build_recoveries(None, HAND)
    assert built.source == DERIVED and built.available
    assert built.frame["derived"].all()
    assert built.types == (SUBROGATION, SALVAGE)  # other recoveries have no to-date field
    assert "derived from subrogation_to_date and salvage_to_date" in built.note
    (found,) = built.findings
    assert (found.rule, found.severity, found.count) == (DERIVED_RULE, "INFO", 5)
    assert "derived" in found.message and "no recoveries feed" in found.message


def test_only_the_to_date_columns_that_exist_are_derived() -> None:
    subrogation_only = HAND.drop("salvage_to_date")
    built = build_recoveries(None, subrogation_only)
    assert built.types == (SUBROGATION,)
    assert set(built.frame["type"]) == {SUBROGATION}


def test_without_a_feed_and_without_to_date_columns_there_are_no_recoveries() -> None:
    bare = HAND.drop("subrogation_to_date", "salvage_to_date")
    built = build_recoveries(None, bare)
    assert built.source == NONE and not built.available
    assert built.frame.height == 0 and built.findings == ()


def test_transactions_win_over_the_to_date_fields() -> None:
    feed = _feed(
        [
            ("R1", "A", date(2024, 2, 10), 40.0, "TRY", SUBROGATION),
            ("R2", "A", date(2024, 3, 5), 20.0, "TRY", SALVAGE),  # the field says 25
            ("R3", "B", date(2024, 2, 20), 15.0, UNKNOWN, SUBROGATION),
            ("R4", "B", date(2024, 3, 1), 7.0, "USD", OTHER),
        ]
    )
    built = build_recoveries(feed, HAND)
    assert built.source == TRANSACTIONS and not built.frame["derived"].any()
    assert built.frame["amount"].sum() == 82.0  # the bookings, not the 75 of the to-date fields
    assert built.types == (SUBROGATION, SALVAGE, OTHER)
    assert "not used" in built.note
    # DV-RCV-03: a booking without a valid currency takes the currency of its claim
    assert built.frame.filter(pl.col("transaction_id") == "R3")["currency"].item() == "USD"


def test_dv_rcv_08_lists_each_difference_with_both_values() -> None:
    feed = _feed(
        [
            ("R1", "A", date(2024, 2, 10), 40.0, "TRY", SUBROGATION),
            ("R2", "A", date(2024, 3, 5), 20.0, "TRY", SALVAGE),
            ("R3", "B", date(2024, 2, 20), 15.0, "USD", SUBROGATION),
        ]
    )
    differences = recovery_differences(feed, HAND)
    rows = differences.select(
        "claim_id", "type", "valuation_date", "booked", "to_date", "difference"
    ).rows()
    assert rows == [
        ("A", SALVAGE, MAR, 20.0, 25.0, -5.0),
        ("A", SALVAGE, APR, 20.0, 25.0, -5.0),
        ("A", SUBROGATION, APR, 40.0, 30.0, 10.0),  # the reversal of April was not booked
        ("B", SALVAGE, MAR, 0.0, 5.0, -5.0),
    ]
    assert differences[SOURCE_ROW].to_list() == [4, 5, 5, 7]


def test_a_difference_of_a_few_cents_is_no_difference() -> None:
    feed = _feed([("R1", "B", date(2024, 2, 20), 15.04, "USD", SUBROGATION)])
    only_b = HAND.filter(pl.col("claim_id") == "B").drop("salvage_to_date")
    assert recovery_differences(feed, only_b).height == 0
    feed = _feed([("R1", "B", date(2024, 2, 20), 15.06, "USD", SUBROGATION)])
    assert recovery_differences(feed, only_b).height == 2
