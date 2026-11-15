"""M08 does not depend on the order of its input rows or of its groups: the tables of a small
treaty programme are the same bytes whatever the order of the treaty and transaction rows, and
in repeated runs (record 0813).

Spec IDs proved: M08, CV09, MT21.
"""

import random
from datetime import date

import polars as pl
import pytest

from actuarycanary.measures.reinsurance_programme import net_share_by_origin
from actuarycanary.modules.reinsurance import reinsurance_run
from tests.measures.helpers import make_inputs
from tests.quality.builders import claim, cv, policy, premium

END = date(2024, 12, 31)
LINES = ("L", "M")
CLAIMS = 48


def _treaties() -> list[dict]:
    rows = []
    for year in (2023, 2024):
        period = {
            "inception_date": date(year, 1, 1),
            "expiry_date": date(year + 1, 1, 1),
            "currency": "TRY",
        }
        for line in LINES:
            rows.append(
                {
                    "treaty_id": f"QS_{line}",
                    "treaty_type": "QUOTA_SHARE",
                    "line": line,
                    "cession_share": 0.3,
                    "ceding_commission": 0.2,
                    **period,
                }
            )
        rows.append(
            {
                "treaty_id": "XL",
                "treaty_type": "EXCESS_OF_LOSS",
                "retention": 400.0,
                "limit": 2000.0,
                "premium_rate": 0.05,
                **period,
            }
        )
    return rows


def _gross(i: int) -> tuple[float, float]:
    """Paid and reserve of claim i: thirds and sevenths, so that float sums feel their order."""
    return (100.0 + 977.0 * i) / 3.0, (50.0 + 331.0 * (i % 9)) / 7.0


def _rows() -> dict[str, list[dict]]:
    claims, valuations, movements = [], [], []
    for i in range(CLAIMS):
        year, line, claim_id = 2023 + i % 2, LINES[i % 3 % 2], f"C{i:02d}"
        paid, reserve = _gross(i)
        claims.append(
            claim(
                claim_id=claim_id,
                occurrence_date=date(year, 1 + i % 12, 3),
                report_date=date(year, 1 + i % 12, 9),
                close_date=None,
                line=line,
                segment="NON_LIFE",
                policy_id=f"P{i % 5}",
            )
        )
        for month, share in ((6, 0.5), (12, 1.0)):
            valuations.append(
                cv(month, claim_id=claim_id, paid_to_date=paid * share, case_reserve=reserve)
            )
        # the reinsurer's account: the quota share of each claim in three movements, one of
        # them a little off, so that the reconciliation has rows on both sides
        for n, (kind, day, amount) in enumerate(
            (
                ("CEDED_CLAIM_PAID", date(2024, 6, 30), 0.3 * paid * 0.5),
                ("CEDED_CLAIM_PAID", END, 0.3 * paid * 0.5 * (1.1 if i % 7 == 0 else 1.0)),
                ("CEDED_CASE_RESERVE", END, 0.3 * reserve),
            )
        ):
            movements.append(
                {
                    "transaction_id": f"{claim_id}-{n}",
                    "treaty_id": f"QS_{line}",
                    "booking_date": day,
                    "amount": amount,
                    "currency": "TRY",
                    "type": kind,
                    "claim_id": claim_id,
                }
            )
    for n, (treaty, kind, month, amount) in enumerate(
        [  # movements without a claim or a policy: allocated by weights (CV09)
            ("XL", "CEDED_CLAIM_PAID", 6, 10000.0 / 3.0),
            ("XL", "CEDED_CLAIM_PAID", 12, 20000.0 / 7.0),
            ("XL", "CEDED_CASE_RESERVE", 12, 5000.0 / 3.0),
            *[(f"QS_{line}", "CEDED_PREMIUM", m, 700.0 / 3.0) for line in LINES for m in (1, 2)],
            *[(f"QS_{line}", "RI_COMMISSION", m, 140.0 / 3.0) for line in LINES for m in (1, 2)],
            ("XL", "CEDED_PREMIUM", 1, 350.0 / 3.0),
        ]
    ):
        movements.append(
            {
                "transaction_id": f"A{n}",
                "treaty_id": treaty,
                "booking_date": date(2024, month, 28),
                "amount": amount,
                "currency": "TRY",
                "type": kind,
            }
        )
    policies = [
        policy(
            policy_id=f"P{p}",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 1),
            segment="NON_LIFE",
            line=LINES[p % 2],
        )
        for p in range(5)
    ]
    premiums = [
        premium(
            transaction_id=f"W{p}{m}",
            policy_id=f"P{p}",
            booking_date=date(2024, m, 5),
            amount=(900.0 + 77.0 * p) / 3.0,
        )
        for p in range(5)
        for m in (1, 2)
    ]
    return {
        "claim_valuations": valuations,
        "claims": claims,
        "policies": policies,
        "premiums": premiums,
        "reinsurance_treaties": _treaties(),
        "reinsurance_transactions": movements,
    }


def _files(rows: dict[str, list[dict]]) -> dict[str, str]:
    """The tables of M08 as the bytes the run would write."""
    inputs = make_inputs(rows, cut_off=END)
    run = reinsurance_run(inputs)
    assert run is not None and run.allocation is not None
    tables: dict[str, pl.DataFrame] = {
        "ceded_by_treaty": run.treaty_table(),
        "reinsurance_reconciliation": run.reconciliation(),
        "ceded_allocation": run.allocation_table(),
        "size_bands": run.size_bands(),
        "reported_claims": run.reported_claims(),
        "allocation_summary": run.allocation.summary(),
        "net_share": net_share_by_origin(run, inputs),
    }
    return {name: table.write_csv(float_precision=None) for name, table in tables.items()}


def test_the_scenario_has_what_the_order_could_move() -> None:
    files = _files(_rows())
    assert all(text.count("\n") > 1 for text in files.values()), files.keys()
    assert "true" in files["reinsurance_reconciliation"]  # a difference with its claim rows
    assert "claims by their computed ceded movement" in files["ceded_allocation"]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_tables_are_the_same_bytes_whatever_the_order_of_the_rows(seed: int) -> None:
    rows = _rows()
    first = _files(rows)
    assert _files(rows) == first  # a second run on the same rows
    shuffled = dict(rows)
    for concept in ("reinsurance_treaties", "reinsurance_transactions"):
        shuffled[concept] = random.Random(seed).sample(rows[concept], len(rows[concept]))
    assert shuffled["reinsurance_transactions"] != rows["reinsurance_transactions"]
    again = _files(shuffled)
    for name in first:
        assert again[name] == first[name], name
