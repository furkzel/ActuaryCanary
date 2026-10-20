"""Policies and premium transactions (spec/data policies and premiums; CV05 signs; PR02)."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.build import simulate
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.feeds import earned_premium
from actuarycanary.synthetic.portfolio import NO_DAY, WRITTEN_TYPES, Policies, PremiumRows
from actuarycanary.synthetic.scenario import SizeSpec, load_scenario


def test_policy_and_transaction_identifiers_are_zero_padded_text(baseline):
    ids = baseline.frames["policies"]["policies"]["policy_id"]
    assert ids.dtype == pl.String
    assert ids[0] == "00000001" and all(len(i) == 8 for i in ids)
    transactions = baseline.frames["premiums"]["premiums"]["transaction_id"]
    assert transactions.dtype == pl.String and transactions[0] == "000000001"


def test_every_policy_runs_for_its_term_and_is_cancelled_inside_its_cover(baseline):
    p = baseline.policies
    assert (p.start < p.end).all()
    assert ((p.end - p.start >= 365) & (p.end - p.start <= 366)).all()
    cancelled = p.cancel != NO_DAY
    assert cancelled.any()
    inside = (p.cancel[cancelled] > p.start[cancelled]) & (p.cancel[cancelled] < p.end[cancelled])
    assert inside.all()
    assert (p.issue <= p.start).all()


def test_policy_counts_scale_with_the_portfolio_scale():
    scenario = load_scenario("baseline")
    small = simulate(scenario, SizeSpec(portfolio_scale=0.001, years=(2024, 2025)))
    large = simulate(scenario, SizeSpec(portfolio_scale=0.002, years=(2024, 2025)))
    assert len(large.policies) / len(small.policies) == pytest.approx(2.0, rel=0.05)


def test_sums_insured_move_with_prices(baseline):
    p = baseline.policies
    od = (p.line == "MOTOR_OD") & (p.currency == "TRY")
    early = od & (p.start < to_day(date(2022, 6, 1)))
    late = od & (p.start >= to_day(date(2025, 1, 1)))
    assert np.median(p.sum_insured[late]) / np.median(p.sum_insured[early]) > 2


def test_premium_signs_follow_cv05(baseline):
    rows = baseline.premiums
    assert {"WRITTEN", "COMMISSION", "CANCELLATION", "CEDED_PREMIUM", "RI_COMMISSION"} <= set(
        rows.type
    )
    assert (rows.amount[rows.type == "WRITTEN"] > 0).all()
    assert (rows.amount[rows.type == "CANCELLATION"] < 0).all()
    assert (rows.amount[rows.type == "REFUND"] < 0).all()
    commission = rows.amount[rows.type == "COMMISSION"]
    assert (commission > 0).mean() > 0.9  # clawbacks on cancellation are the only reversals


def test_one_written_row_per_policy_and_the_commission_rate(baseline):
    rows, p = baseline.premiums, baseline.policies
    written = rows.type == "WRITTEN"
    assert written.sum() == len(p)
    assert (rows.amount[written] == p.premium[rows.policy[written]]).all()
    first_od = int(np.flatnonzero(p.line == "MOTOR_OD")[0])
    commission = rows.amount[(rows.policy == first_od) & (rows.type == "COMMISSION")]
    assert commission[0] == pytest.approx(0.15 * p.premium[first_od], abs=0.011)


def test_cancellation_returns_the_unexpired_share_of_the_premium(baseline):
    rows, p = baseline.premiums, baseline.policies
    i = int(np.flatnonzero(rows.type == "CANCELLATION")[0])
    pol = int(rows.policy[i])
    unexpired = (p.end[pol] - p.cancel[pol]) / (p.end[pol] - p.start[pol])
    assert rows.amount[i] == pytest.approx(-p.premium[pol] * unexpired, abs=0.011)
    assert rows.booking[i] == rows.effective[i] == p.cancel[pol]


def test_quota_share_cedes_its_share_of_written_premium_and_pays_its_commission(baseline):
    rows, p = baseline.premiums, baseline.policies
    ceded = rows.amount[(rows.treaty == "QS_PROPERTY") & (rows.type == "CEDED_PREMIUM")]
    commission = rows.amount[(rows.treaty == "QS_PROPERTY") & (rows.type == "RI_COMMISSION")]
    gross = rows.amount[np.isin(rows.type, WRITTEN_TYPES) & (p.line[rows.policy] == "PROPERTY")]
    assert len(ceded) == len(commission) > 0
    assert ceded.sum() == pytest.approx(0.30 * gross.sum(), rel=1e-3)
    assert commission.sum() == pytest.approx(0.25 * ceded.sum(), rel=1e-3)


def test_earned_premium_spreads_a_leap_year_policy_by_day():
    """PR02 and CV04: 366 days of cover and a premium of 366 earn one unit a day."""
    start, end = to_day(date(2024, 1, 1)), to_day(date(2025, 1, 1))
    policies = Policies(
        line=np.array(["L"], dtype=object),
        entity=np.array(["E"], dtype=object),
        product=np.array(["P"], dtype=object),
        partner=np.array(["X"], dtype=object),
        channel=np.array(["AGENCY"], dtype=object),
        currency=np.array(["TRY"], dtype=object),
        start=np.array([start]),
        end=np.array([end]),
        issue=np.array([start]),
        cancel=np.array([NO_DAY]),
        sum_insured=np.array([0.0]),
        units=np.array([1.0]),
        premium=np.array([366.0]),
    )
    rows = PremiumRows(
        np.array([0]),
        np.array([start]),
        np.array([start]),
        np.array([366.0]),
        np.array(["WRITTEN"], dtype=object),
        np.array([""], dtype=object),
    )
    monthly, first_month, last_month = earned_premium(policies, rows, ["L"], ["E"], ["TRY"])
    assert monthly.shape == (1, 12) and last_month - first_month == 11
    assert monthly[0, 0] == pytest.approx(31.0)  # January
    assert monthly[0, 1] == pytest.approx(29.0)  # leap February
    assert monthly.sum() == pytest.approx(366.0)
