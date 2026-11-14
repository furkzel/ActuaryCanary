"""A hand-worked reinsurance book shared by the RI03 to RI05 and M08 tests.

Four claims of 2024 on line L (incurred 100, 300, 50, 500; paid 100, 200, 50, 400) under a
30 % quota share with 20 % commission and, inuring after it, an excess of loss 250 xs 200 at a
premium rate of 5 % of GNPI. Written premium 1000. The quota share cedes 0.3 of each claim
(285 in all); the layer sees 70, 210, 35, 350 and cedes 10 (B, all reserve) and 150 (D: 80 paid,
70 reserve). Ceded premium: 300 to the quota share, 0.05 x 700 = 35 to the layer.
"""

from datetime import date

from tests.measures.helpers import make_inputs
from tests.quality.builders import claim, cv, policy, premium

YEAR = {"inception_date": date(2024, 1, 1), "expiry_date": date(2025, 1, 1), "currency": "TRY"}
END = date(2024, 12, 31)
GROSS = {"A": (100.0, 0.0), "B": (200.0, 100.0), "C": (50.0, 0.0), "D": (400.0, 100.0)}
QS_CEDED = {k: (0.3 * p, 0.3 * r) for k, (p, r) in GROSS.items()}
XL_CEDED = {"B": (0.0, 10.0), "D": (80.0, 70.0)}


def treaties() -> list[dict]:
    return [
        {
            "treaty_id": "QS",
            "treaty_type": "QUOTA_SHARE",
            "line": "L",
            "cession_share": 0.3,
            "ceding_commission": 0.2,
            **YEAR,
        },
        {
            "treaty_id": "XL",
            "treaty_type": "EXCESS_OF_LOSS",
            "line": "L",
            "retention": 200.0,
            "limit": 250.0,
            "premium_rate": 0.05,
            **YEAR,
        },
    ]


def movements(qs_paid_d: float = 120.0) -> list[dict]:
    rows: list[dict] = []
    n = 0
    for treaty, ceded in (("QS", QS_CEDED), ("XL", XL_CEDED)):
        for claim_id, (paid, reserve) in ceded.items():
            if treaty == "QS" and claim_id == "D":
                paid = qs_paid_d
            for kind, amount in (("CEDED_CLAIM_PAID", paid), ("CEDED_CASE_RESERVE", reserve)):
                n += 1
                rows.append(
                    {
                        "transaction_id": str(n),
                        "treaty_id": treaty,
                        "booking_date": END,
                        "amount": amount,
                        "currency": "TRY",
                        "type": kind,
                        "claim_id": claim_id,
                    }
                )
    rows += [
        {
            "transaction_id": "P1",
            "treaty_id": "QS",
            "booking_date": date(2024, 1, 31),
            "amount": 300.0,
            "currency": "TRY",
            "type": "CEDED_PREMIUM",
        },
        {
            "transaction_id": "P2",
            "treaty_id": "QS",
            "booking_date": date(2024, 1, 31),
            "amount": 60.0,
            "currency": "TRY",
            "type": "RI_COMMISSION",
        },
        {
            "transaction_id": "P3",
            "treaty_id": "XL",
            "booking_date": date(2024, 1, 31),
            "amount": 35.0,
            "currency": "TRY",
            "type": "CEDED_PREMIUM",
        },
    ]
    return rows


def book(qs_paid_d: float = 120.0, **extra):
    """The measure inputs of the book; `qs_paid_d` changes one reported movement."""
    valuations = []
    for claim_id, (paid, reserve) in GROSS.items():
        ceded_paid = QS_CEDED[claim_id][0] + XL_CEDED.get(claim_id, (0.0, 0.0))[0]
        ceded_reserve = QS_CEDED[claim_id][1] + XL_CEDED.get(claim_id, (0.0, 0.0))[1]
        valuations.append(
            cv(
                12,
                claim_id=claim_id,
                paid_to_date=paid,
                case_reserve=reserve,
                ceded_paid_to_date=ceded_paid,
                ceded_reserve=ceded_reserve,
            )
        )
    rows = {
        "claim_valuations": valuations,
        "claims": [
            claim(
                claim_id=c,
                occurrence_date=date(2024, i + 2, 1),
                report_date=date(2024, i + 2, 5),
                close_date=None,
                line="L",
                segment="NON_LIFE",
                policy_id="P1",
            )
            for i, c in enumerate(GROSS)
        ],
        "policies": [
            policy(
                start_date=date(2024, 1, 1), end_date=date(2025, 1, 1), segment="NON_LIFE", line="L"
            )
        ],
        "premiums": [premium(transaction_id="W1", booking_date=date(2024, 1, 5), amount=1000.0)],
        "reinsurance_treaties": treaties(),
        "reinsurance_transactions": movements(qs_paid_d),
    }
    return make_inputs(rows, cut_off=END, **extra)
