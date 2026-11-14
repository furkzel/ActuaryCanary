"""RI04 Reinsurance result ratio: hand figures for two origins, with ceded incurred (no ceded
selection is built: the incurred view, labelled), commission and reinstatement premium.

Spec IDs proved: RI04.
"""

from datetime import date

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.measures.reinsurance_programme import INCURRED_VIEW
from tests.measures.helpers import make_inputs, measure
from tests.quality.builders import claim, cv, policy, premium


def _inputs():
    def year(y: int) -> dict:
        return {
            "inception_date": date(y, 1, 1),
            "expiry_date": date(y + 1, 1, 1),
            "currency": "TRY",
        }

    rows = {
        "claim_valuations": [
            cv(
                12,
                claim_id="E",
                paid_to_date=300.0,
                case_reserve=100.0,
                ceded_paid_to_date=100.0,
                ceded_reserve=20.0,
            ),
            cv(
                12,
                claim_id="F",
                paid_to_date=200.0,
                case_reserve=100.0,
                ceded_paid_to_date=60.0,
                ceded_reserve=30.0,
            ),
        ],
        "claims": [
            claim(
                claim_id="E",
                occurrence_date=date(2023, 6, 1),
                report_date=date(2023, 6, 2),
                close_date=None,
                line="L",
                segment="NON_LIFE",
                policy_id="P23",
            ),
            claim(
                claim_id="F",
                occurrence_date=date(2024, 6, 1),
                report_date=date(2024, 6, 2),
                close_date=None,
                line="L",
                segment="NON_LIFE",
                policy_id="P24",
            ),
        ],
        "policies": [
            policy(
                policy_id="P23",
                start_date=date(2023, 1, 1),
                end_date=date(2024, 1, 1),
                segment="NON_LIFE",
                line="L",
            ),
            policy(
                policy_id="P24",
                start_date=date(2024, 1, 1),
                end_date=date(2025, 1, 1),
                segment="NON_LIFE",
                line="L",
            ),
        ],
        "premiums": [
            premium(
                transaction_id="W23", policy_id="P23", booking_date=date(2023, 1, 1), amount=1000.0
            ),
            premium(
                transaction_id="C23",
                policy_id="P23",
                booking_date=date(2023, 1, 1),
                amount=300.0,
                type="CEDED_PREMIUM",
            ),
            premium(
                transaction_id="K23",
                policy_id="P23",
                booking_date=date(2023, 1, 1),
                amount=60.0,
                type="RI_COMMISSION",
            ),
            premium(
                transaction_id="W24", policy_id="P24", booking_date=date(2024, 1, 1), amount=2000.0
            ),
            premium(
                transaction_id="C24",
                policy_id="P24",
                booking_date=date(2024, 1, 1),
                amount=600.0,
                type="CEDED_PREMIUM",
            ),
            premium(
                transaction_id="K24",
                policy_id="P24",
                booking_date=date(2024, 1, 1),
                amount=120.0,
                type="RI_COMMISSION",
            ),
        ],
        "reinsurance_treaties": [
            {
                "treaty_id": "QS",
                "treaty_type": "QUOTA_SHARE",
                "line": "L",
                "cession_share": 0.3,
                **year(y),
            }
            for y in (2023, 2024)
        ],
        "reinsurance_transactions": [
            {
                "transaction_id": "R1",
                "treaty_id": "QS",
                "booking_date": date(2024, 12, 31),
                "amount": 10.0,
                "currency": "TRY",
                "type": "REINSTATEMENT_PREMIUM",
            },
        ],
    }
    return make_inputs(rows, cut_off=date(2024, 12, 31))


def test_ri04_two_origins_by_hand() -> None:
    result = measure(_inputs(), "RI04", "origin_period", reinsurance=ReinsuranceBasis.CEDED)
    assert result.frame is not None, result.reason
    got = {r["origin_period"]: r for r in result.frame.iter_rows(named=True)}
    # 2023: (ceded incurred 120 + commission 60 - ceded premium 300) / earned 1000
    assert got["2023"]["value"] == pytest.approx((120 + 60 - 300) / 1000, rel=1e-9)
    # 2024: (90 + 120 - 600 - reinstatement premium 10) / 2000
    assert got["2024"]["reinstatement_premium"] == pytest.approx(10.0)
    assert got["2024"]["value"] == pytest.approx((90 + 120 - 600 - 10) / 2000, rel=1e-9)
    assert got["2024"]["note"] == INCURRED_VIEW
    assert INCURRED_VIEW in result.notes
