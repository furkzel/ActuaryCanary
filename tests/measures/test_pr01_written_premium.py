"""PR01 Written premium: hand-computed fixtures of the specification."""

from datetime import date

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.measures.model import CurrencyView
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.periods import Period
from tests.canonical.test_feeds import _table
from tests.measures.helpers import make_inputs, measure, one, table
from tests.measures.shared import premium_inputs, pt, year_policy
from tests.quality.builders import cv


def test_pr01_written_premium_on_gross_ceded_and_net_with_cv05_signs() -> None:
    """A CANCELLATION stored positive is turned negative by CV05; the UNMAPPED row is left out;
    March has one more written row. Gross Jan 1100, Feb -165, Mar 500; ceded 300 in January."""

    def row(number: int, kind: str, day: date, amount: float) -> dict:
        return {
            "transaction_id": f"T{number}",
            "policy_id": "P1",
            "booking_date": day,
            "amount": amount,
            "currency": "TRY",
            "type": kind,
        }

    raw = [
        row(1, "WRITTEN", date(2024, 1, 10), 1000.0),
        row(2, "ENDORSEMENT", date(2024, 1, 20), 100.0),
        row(3, "CANCELLATION", date(2024, 2, 5), 110.0),  # stored positive: CV05 negates it
        row(4, "REFUND", date(2024, 2, 10), -55.0),
        row(5, "CEDED_PREMIUM", date(2024, 1, 10), 300.0),
        row(6, "SOMETHING", date(2024, 1, 12), 99.0),  # UNMAPPED: left out
        row(7, "WRITTEN", date(2024, 3, 5), 500.0),
    ]
    feed = canonicalise(_table(raw, "premiums"), load_specs().data["premiums"])
    inputs = make_inputs({"claim_valuations": [cv(3)], "premiums": []}, cut_off=date(2024, 3, 31))
    inputs.feeds = {**inputs.feeds, "premiums": feed.frame.with_row_index("_ref")}  # type: ignore[misc]
    gross = measure(inputs, "PR01", "calendar_period", period=Period.MONTH)
    assert table(gross) == {("2024-01",): 1100.0, ("2024-02",): -165.0, ("2024-03",): 500.0}
    ceded = measure(
        inputs, "PR01", "calendar_period", period=Period.MONTH, reinsurance=ReinsuranceBasis.CEDED
    )
    assert table(ceded) == {("2024-01",): 300.0, ("2024-02",): 0.0, ("2024-03",): 0.0}
    net = measure(
        inputs, "PR01", "calendar_period", period=Period.MONTH, reinsurance=ReinsuranceBasis.NET
    )
    assert table(net) == {("2024-01",): 800.0, ("2024-02",): -165.0, ("2024-03",): 500.0}
    assert "2024-04" not in {
        k[0] for k in table(gross)
    }  # after the last booking month: missing, not 0


def test_pr01_a_period_inside_the_file_without_rows_is_zero() -> None:
    rows = [
        pt("T1", "WRITTEN", date(2024, 1, 10), 100.0),
        pt("T2", "WRITTEN", date(2024, 3, 10), 50.0),
    ]
    result = measure(premium_inputs(rows), "PR01", "calendar_period", period=Period.MONTH)
    assert table(result) == {("2024-01",): 100.0, ("2024-02",): 0.0, ("2024-03",): 50.0}


def test_pr01_breakdown_by_policy_attribute_and_unknown_policy() -> None:
    rows = [
        pt("T1", "WRITTEN", date(2024, 1, 10), 100.0),
        pt("T2", "WRITTEN", date(2024, 1, 11), 40.0, policy_id="GONE"),
    ]
    inputs = premium_inputs(rows, [year_policy()])
    assert table(measure(inputs, "PR01", "segment")) == {("S",): 100.0, ("UNKNOWN",): 40.0}
    without = measure(premium_inputs(rows), "PR01", "segment")
    assert without.reason == "breakdowns segment need policies, which are not loaded"


def test_pr01_original_view_shows_each_currency_apart() -> None:
    rows = [
        pt("T1", "WRITTEN", date(2024, 1, 10), 100.0),
        pt("T2", "WRITTEN", date(2024, 1, 11), 7.0, currency="USD"),
    ]
    result = measure(premium_inputs(rows), "PR01", currency=CurrencyView.ORIGINAL)
    assert table(result) == {("TRY",): 100.0, ("USD",): 7.0}
    converted = measure(premium_inputs(rows), "PR01")
    assert one(converted) == 100.0 and any("USD" in n for n in converted.notes)
