"""Fixtures shared by several measure tests."""

from datetime import date

import polars as pl

from actuarycanary.measures.port import NotAvailable, Selection
from tests.measures.helpers import make_inputs
from tests.quality.builders import claim, cv, policy, premium
from tests.structures.test_premium import TRANSACTIONS

FEB29, MAR31 = date(2024, 2, 29), date(2024, 3, 31)


YEAR_END = date(2024, 12, 31)


class Selected:
    """A port that answers with a fixed selection, as the methods will."""

    def __init__(self, selection: Selection | NotAvailable) -> None:
        self._selection = selection

    def selection(self, valuation_date: date, basis: str = "") -> Selection | NotAvailable:
        return self._selection

    def measure(self, measure_id: str, basis: str = "") -> pl.DataFrame | NotAvailable:
        return NotAvailable("not part of the stub")

    def built(self) -> frozenset[str]:
        return frozenset({"MT10"})


JAN31, FEB29, MAR31, APR30 = (
    date(2024, 1, 31),
    date(2024, 2, 29),
    date(2024, 3, 31),
    date(2024, 4, 30),
)


def premium_inputs(premiums: list[dict], policies: list[dict] | None = None, **extra):
    rows = {"claim_valuations": [cv(1)], "premiums": premiums}
    if policies is not None:
        rows["policies"] = policies
    return make_inputs(rows, cut_off=extra.pop("cut_off", YEAR_END), **extra)


FOUR_MONTHS = [
    cv(1, claim_id="A", paid_to_date=100.0, case_reserve=500.0),
    cv(2, claim_id="A", paid_to_date=150.0, case_reserve=400.0),
    cv(3, claim_id="A", paid_to_date=150.0, case_reserve=400.0),
    cv(4, claim_id="A", paid_to_date=200.0, case_reserve=300.0),
    cv(1, claim_id="B", paid_to_date=0.0, case_reserve=100.0),
    cv(3, claim_id="B", paid_to_date=50.0, case_reserve=60.0),
    cv(4, claim_id="B", paid_to_date=80.0, case_reserve=20.0),
    cv(1, claim_id="C", paid_to_date=300.0, case_reserve=200.0),
    cv(2, claim_id="C", paid_to_date=250.0, case_reserve=200.0),
    cv(3, claim_id="C", paid_to_date=250.0, case_reserve=150.0),
    cv(4, claim_id="C", paid_to_date=250.0, case_reserve=150.0),
]


def pt(
    transaction: str,
    kind: str,
    booked: date,
    amount: float,
    effective: date | None = None,
    **more,
):
    """A premium transaction row with its id first."""
    return premium(
        transaction_id=transaction,
        type=kind,
        booking_date=booked,
        amount=amount,
        effective_date=effective,
        **more,
    )


def p(kind: str, amount: float, booked: date = date(2024, 1, 1), n: int = 1, **more):
    return premium(
        transaction_id=f"{kind}{n}", type=kind, amount=amount, booking_date=booked, **more
    )


MONTH_ENDS = (JAN31, FEB29, MAR31, APR30)


def year_policy(**more):
    return policy(
        start_date=date(2024, 1, 1), end_date=date(2025, 1, 1), segment="S", line="L", **more
    )


def four_months():
    return make_inputs({"claim_valuations": FOUR_MONTHS})


def inputs_for(premiums=(), expenses=None, claims_rows=None, claims=None, **extra):
    rows = {
        "claim_valuations": claims_rows or [cv(12, claim_id="K0")],
        "premiums": list(premiums),
        "policies": [year_policy()],
    }
    if expenses is not None:
        rows["expenses"] = expenses
    if claims is not None:
        rows["claims"] = claims
    return make_inputs(rows, cut_off=YEAR_END, **extra)


def _earning_inputs():
    rows = [
        pt(t, kind, booked, amount, effective)
        for t, kind, booked, effective, amount in TRANSACTIONS
    ]
    return premium_inputs(
        rows,
        [policy(segment="S", line="L", start_date=date(2024, 7, 1), end_date=date(2025, 7, 1))],
        cut_off=date(2025, 7, 31),
    )


BOOKED = date(2024, 1, 15)


def _loss_inputs(
    extra_premiums=(), expenses=None, ultimate: Selection | NotAvailable | None = None
):
    claims_rows = [cv(12, claim_id="K0", paid_to_date=400.0, case_reserve=250.0)]
    claims = [claim(claim_id="K0", segment="S", line="L", occurrence_date=date(2024, 5, 1))]
    selection = ultimate or Selection(YEAR_END, {("S", "L", "2024"): 720.0})
    return inputs_for(
        [p("WRITTEN", 1000.0), *extra_premiums],
        expenses,
        claims_rows,
        claims,
        methods=Selected(selection),
    )
