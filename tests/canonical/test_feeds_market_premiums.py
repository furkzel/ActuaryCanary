"""Row rules of the market, premiums and policies feeds that decide what enters conversion,
restatement and premium structures (DV-MKT, DV-PRM, DV-POL, CV05)."""

from datetime import date
from typing import Any

from actuarycanary.canonical.feeds import UNKNOWN, UNMAPPED, CanonicalFeed, canonicalise
from actuarycanary.spec.loader import load_specs
from tests.canonical.test_feeds import _rules, _table

SPECS = load_specs()


def _feed(concept: str, rows: list[dict[str, Any]]) -> CanonicalFeed:
    return canonicalise(_table(rows, concept), SPECS.data[concept])


def _market(series: str, kind: str, day: date | None, value: float | None) -> dict[str, Any]:
    return {"series_id": series, "kind": kind, "date": day, "value": value}


def test_market_rows_are_excluded_by_dv_mkt_01_03_04_05() -> None:
    feed = _feed(
        "market",
        [
            _market("USD/TRY", "FX_SPOT", date(2024, 1, 2), 30.0),
            _market("USD/TRY", "FX_SPOT", None, 30.0),  # DV-MKT-01
            _market("USD/TRY", "FX_SPOT", date(2024, 1, 3), -1.0),  # DV-MKT-03
            _market("USD", "FX_SPOT", date(2024, 1, 4), 30.0),  # DV-MKT-04: not BASE/QUOTE
            _market("CPI_TR", "FX_SPOT", date(2024, 1, 5), 30.0),  # DV-MKT-04
            _market("USD/USD", "FX_SPOT", date(2024, 1, 6), 1.0),  # DV-MKT-04: same codes
            _market("USD/TRY", "WEIRD", date(2024, 1, 7), 30.0),  # DV-MKT-05
            _market("CPI_TR", "PRICE_INDEX", date(2024, 1, 31), 100.0),
        ],
    )
    assert feed.frame["series_id"].to_list() == ["USD/TRY", "CPI_TR"]
    assert _rules(feed) == {"DV-MKT-01": 1, "DV-MKT-03": 1, "DV-MKT-04": 3, "DV-MKT-05": 1}


def test_market_conflicting_values_keep_the_later_date_in_the_month_then_the_later_row() -> None:
    feed = _feed(
        "market",
        [
            _market("CPI_TR", "PRICE_INDEX", date(2024, 1, 31), 100.0),
            _market("CPI_TR", "PRICE_INDEX", date(2024, 1, 15), 99.0),  # earlier date loses
            _market("USD/TRY", "FX_SPOT", date(2024, 1, 2), 30.0),
            _market("USD/TRY", "FX_SPOT", date(2024, 1, 2), 31.0),  # same date: later row wins
            _market("USD/TRY", "FX_SPOT", date(2024, 1, 3), 32.0),  # another day: not a duplicate
        ],
    )
    assert sorted(feed.frame["value"].to_list()) == [31.0, 32.0, 100.0]
    assert _rules(feed) == {"DV-MKT-02": 2}


def _premium(txn: str | None, kind: str, amount: float | None, **values: Any) -> dict[str, Any]:
    row = {
        "transaction_id": txn,
        "policy_id": "P1",
        "booking_date": date(2024, 1, 1),
        "amount": amount,
        "currency": "TRY",
        "type": kind,
    }
    return row | values


def test_premium_rows_are_excluded_or_marked_by_dv_prm_01_to_05() -> None:
    feed = _feed(
        "premiums",
        [
            _premium("T1", "WRITTEN", 100.0),
            _premium(None, "WRITTEN", 100.0),  # DV-PRM-01
            _premium("T1", "WRITTEN", 100.0),  # DV-PRM-02 identical
            _premium("T1", "WRITTEN", 999.0),  # DV-PRM-02 conflicting
            _premium("T2", "WRITTEN", None),  # DV-PRM-03
            _premium("T3", "ODD", 5.0),  # DV-PRM-04
            _premium("T4", "WRITTEN", 5.0, currency="??"),  # DV-PRM-05
        ],
    )
    assert feed.frame["transaction_id"].to_list() == ["T1", "T3", "T4"]
    assert feed.frame["type"].to_list() == ["WRITTEN", UNMAPPED, "WRITTEN"]
    assert feed.frame["currency"].to_list() == ["TRY", "TRY", UNKNOWN]
    assert _rules(feed) == {
        "DV-PRM-01": 1,
        "DV-PRM-02": 2,
        "DV-PRM-03": 1,
        "DV-PRM-04": 1,
        "DV-PRM-05": 1,
    }


def test_cv05_a_type_stored_with_the_opposite_sign_is_flipped_as_a_whole() -> None:
    feed = _feed(
        "premiums",
        [
            _premium("T1", "WRITTEN", 100.0),
            _premium("T2", "CANCELLATION", 30.0),  # canonical sign is negative
            _premium("T3", "CANCELLATION", 20.0),
            _premium("T4", "CANCELLATION", -10.0),  # a reversal in a flipped type stays opposite
            _premium("T5", "ENDORSEMENT", -50.0),  # either sign: never flipped
        ],
    )
    assert feed.frame["amount"].to_list() == [100.0, -30.0, -20.0, 10.0, -50.0]
    assert _rules(feed) == {"DV-PRM-08": 3}


def test_cv05_a_minority_of_opposite_signs_is_kept_as_reversals() -> None:
    feed = _feed(
        "premiums",
        [
            _premium("T1", "WRITTEN", 100.0),
            _premium("T2", "WRITTEN", 50.0),
            _premium("T3", "WRITTEN", -20.0),
        ],
    )
    assert feed.frame["amount"].to_list() == [100.0, 50.0, -20.0]
    assert _rules(feed) == {}


def test_policy_rows_follow_dv_pol_01_to_08() -> None:
    def policy(pid: str | None, **values: Any) -> dict[str, Any]:
        row = {
            "policy_id": pid,
            "start_date": date(2024, 1, 1),
            "end_date": date(2025, 1, 1),
            "segment": "NON_LIFE",
            "line": "MOTOR_OD",
            "currency": "TRY",
        }
        return row | values

    feed = _feed(
        "policies",
        [
            policy("P1"),
            policy(None),  # DV-POL-01
            policy("P1"),  # DV-POL-02 identical
            policy("P2", start_date=None),  # DV-POL-03
            policy("P3", segment=None, line=None),  # DV-POL-03 x2
            policy("P4", end_date=date(2024, 1, 1)),  # DV-POL-04
            policy("P5", cancellation_date=date(2026, 1, 1)),  # DV-POL-05
            policy("P6", currency="??"),  # DV-POL-06
            policy("P7", segment="MARINE"),  # DV-POL-07
            policy("P8", exposure_units=-2.0),  # DV-POL-08
        ],
    )
    rules = _rules(feed)
    for rule in ("DV-POL-01", "DV-POL-02", "DV-POL-04", "DV-POL-05", "DV-POL-06", "DV-POL-07"):
        assert rules[rule] == 1
    assert rules["DV-POL-03"] == 3 and rules["DV-POL-08"] == 1
    by_id = {r["policy_id"]: r for r in feed.frame.iter_rows(named=True)}
    assert by_id["P3"]["segment"] == UNKNOWN and by_id["P3"]["line"] == UNKNOWN
    assert by_id["P5"]["cancellation_date"] is None  # ignored for exposure
    assert by_id["P7"]["segment"] == UNMAPPED
    assert by_id["P8"]["exposure_units"] == 0.0
