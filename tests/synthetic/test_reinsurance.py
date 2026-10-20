"""Ceded amounts: quota share, per-claim excess of loss, per-event excess of loss (CV03)."""

import numpy as np
import pytest

from actuarycanary.synthetic.claims import CATASTROPHE, END_OF_TIME
from tests.synthetic.conftest import simulate_with

# every third-party claim is a tail claim, and the layer starts low, so the layer is hit often
HEAVY_TPL = {
    "lines": {
        "MOTOR_TPL": {
            "severity": {
                "tail": {"probability": 1.0, "dist": "pareto", "threshold": 400000, "alpha": 2.0}
            }
        }
    },
    "reinsurance": [
        {
            "treaty_id": "QS_PROPERTY",
            "type": "QUOTA_SHARE",
            "lines": ["PROPERTY"],
            "cession": 0.3,
            "commission": 0.25,
            "inception": "2016-01-01",
        },
        {
            "treaty_id": "XL_TPL",
            "type": "EXCESS_OF_LOSS",
            "lines": ["MOTOR_TPL"],
            "retention": 1000000,
            "limit": 3000000,
            "retention_indexed_to": "CPI_TR",
            "rate_on_gross_premium": 0.02,
            "inception": "2016-01-01",
        },
        {
            "treaty_id": "XL_CAT",
            "type": "EXCESS_OF_LOSS",
            "lines": ["PROPERTY"],
            "basis": "event",
            "retention": 1000,
            "limit": 5000000,
            "retention_indexed_to": "CPI_TR",
            "rate_on_gross_premium": 0.05,
            "inception": "2016-01-01",
        },
    ],
}


@pytest.fixture(scope="module")
def heavy():
    return simulate_with(HEAVY_TPL)


def test_a_quota_share_cedes_its_share_of_every_amount(baseline):
    w, ri = baseline.world, baseline.reinsurance
    claim = np.flatnonzero((w.c_line == "PROPERTY") & (w.c_kind != CATASTROPHE))
    state = w.state(claim, np.full(len(claim), END_OF_TIME))
    ceded, _ = ri.ceded(claim, np.full(len(claim), END_OF_TIME), state["paid"], state["reserve"])
    assert claim.size > 0
    assert ceded == pytest.approx(0.30 * state["paid"], abs=1e-6)


def test_lines_without_a_treaty_cede_nothing(baseline):
    w, ri = baseline.world, baseline.reinsurance
    claim = np.flatnonzero(w.c_line == "MOTOR_OD")
    state = w.state(claim, np.full(len(claim), END_OF_TIME))
    ceded_paid, ceded_reserve = ri.ceded(
        claim, np.full(len(claim), END_OF_TIME), state["paid"], state["reserve"]
    )
    assert (ceded_paid == 0).all() and (ceded_reserve == 0).all()


def test_a_per_claim_excess_of_loss_pays_the_slice_between_retention_and_limit(heavy):
    w, ri = heavy.world, heavy.reinsurance
    claim = np.flatnonzero(w.c_line == "MOTOR_TPL")
    day = np.full(len(claim), END_OF_TIME)
    paid = w.state(claim, day)["paid"]
    ceded, _ = ri.ceded(claim, day, paid, np.zeros(len(claim)))
    retention = 1_000_000 * heavy.market.price_factor(w.c_occ[claim])
    expected = np.clip(paid - retention, 0, 3_000_000 * heavy.market.price_factor(w.c_occ[claim]))
    assert (expected > 0).sum() > 5
    assert ceded == pytest.approx(expected, rel=1e-9, abs=1e-6)


def test_a_per_claim_layer_adds_the_reserve_to_reach_the_layer_before_payments_do(heavy):
    w, ri = heavy.world, heavy.reinsurance
    claim = np.flatnonzero(w.c_line == "MOTOR_TPL")
    day = w.c_rep[claim] + 1
    state = w.state(claim, day)
    ceded_paid, ceded_reserve = ri.ceded(claim, day, state["paid"], state["reserve"])
    assert (ceded_reserve >= 0).all() and (ceded_reserve <= state["reserve"] + 1e-9).all()
    assert (ceded_paid <= state["paid"] + 1e-9).all()
    assert (ceded_reserve > 0).any()  # some claims are in the layer on their estimate alone


def test_an_event_layer_pays_on_the_event_total_not_on_single_claims(heavy):
    w, ri = heavy.world, heavy.reinsurance
    for event in range(len(w.event_codes)):
        members = np.flatnonzero(w.c_event == event)
        day = np.full(len(members), END_OF_TIME)
        paid = w.state(members, day)["paid"]
        ceded, _ = ri.ceded(members, day, paid, np.zeros(len(members)))
        scale = float(heavy.market.price_factor(np.array([w.event_dates[event]]))[0])
        retained = 0.7 * paid.sum()  # the quota share has already taken 30 per cent
        layer = np.clip(retained - 1_000 * scale, 0, 5_000_000 * scale)
        quota = 0.3 * paid.sum()
        assert ceded.sum() == pytest.approx(quota + layer, rel=1e-9)
        assert layer > 0


def test_net_is_gross_minus_ceded_and_never_negative_in_the_valuations(heavy):
    rows = heavy.clean["claim_valuations"]
    assert ((rows["paid_to_date"] - rows["ceded_paid_to_date"]) >= -1e-9).all()
    assert ((rows["case_reserve"] - rows["ceded_reserve"]) >= -1e-9).all()
    assert (rows["ceded_paid_to_date"] > 0).any()


def test_an_excess_of_loss_cannot_cover_foreign_currency_claims():
    with pytest.raises(ValueError, match="foreign"):
        simulate_with(
            {
                "lines": {
                    "MOTOR_TPL": {
                        "portfolio": {
                            "foreign_currency_share": 1.0,
                            "foreign_currencies": {"USD": 1.0},
                        }
                    }
                }
            }
        )
