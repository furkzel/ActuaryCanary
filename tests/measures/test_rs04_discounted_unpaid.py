"""RS04 discounted unpaid claims on a small triangle, by hand.

Spec IDs proved: RS04, CV10. Cash flows of 100 at 0.5 and 1.5 years with a flat 10 per cent annual
curve give 100 / 1.1^0.5 + 100 / 1.1^1.5; the pattern of the paid chain ladder is scaled to the
selected unpaid and discounted with the timing of CV10; the tail is spread as CV10 says.
"""

from datetime import date

import numpy as np
import pytest

from actuarycanary.convert.discount import DiscountContext, Timing
from actuarycanary.convert.yield_curve import YieldCurve
from actuarycanary.methods.chain_ladder import ChainLadder, chain_ladder
from actuarycanary.modules.uncertainty import _pattern, _scaled_flows
from tests.methods.helpers import HAND, array

CUT_OFF = date(2024, 12, 31)


def fitted(tail_factor: float = 1.0) -> ChainLadder:
    result = chain_ladder(array(HAND["paid"]), min_origins=4, tail_factor=tail_factor)
    assert isinstance(result, ChainLadder)
    return result


def flat_curve(rate: float = 0.10) -> YieldCurve:
    tenors = np.array([1.0, 10.0])
    return YieldCurve(
        "C", CUT_OFF, "TRY", "SPOT", "ANNUAL", "TEST", tenors, np.log1p(rate) * tenors
    )


def context(timing: Timing = Timing.MID_PERIOD, tail_years: int = 5) -> DiscountContext:
    return DiscountContext(flat_curve(), "", CUT_OFF, timing, tail_years)


def test_the_spec_example_two_cash_flows_at_a_flat_ten_per_cent() -> None:
    factors = flat_curve().discount_factors(np.array([0.5, 1.5]))
    assert 100 * factors.sum() == pytest.approx(100 / 1.1**0.5 + 100 / 1.1**1.5, rel=1e-14)


def test_the_hand_triangle_flows_follow_the_chain_ladder_pattern_and_the_selected_unpaid() -> None:
    chain = fitted()
    flows, weights, notes = _pattern(chain, None, tail_periods=5)
    assert notes == () and weights.sum() == pytest.approx(1.0)
    # origin 3 has only its first column: ultimate = latest x cdf[0], flows by the pattern
    ultimate = chain.latest[3] * chain.cdf[0]
    expected = ultimate * (1 / chain.cdf[1:] - 1 / chain.cdf[:-1])
    np.testing.assert_allclose(flows[3, :3], expected, rtol=1e-13)
    assert flows[0].sum() == pytest.approx(0.0, abs=1e-9)  # the oldest origin is developed
    np.testing.assert_allclose(flows.sum(axis=1), chain.reserve, rtol=1e-12, atol=1e-9)
    # a selected unpaid other than the chain-ladder reserve rescales each origin
    selected = chain.reserve * 1.5
    scaled, scale_notes = _scaled_flows(flows, selected, ("A", "B", "C", "D"))
    np.testing.assert_allclose(scaled.sum(axis=1), selected, rtol=1e-12, atol=1e-9)
    assert any("origin A" in note for note in scale_notes) or flows[0].sum() == pytest.approx(
        0, abs=1e-9
    )


def test_an_origin_without_a_pattern_but_with_a_selected_unpaid_falls_in_period_one() -> None:
    flows = np.zeros((2, 3))
    flows[1] = [10.0, 20.0, 30.0]
    scaled, notes = _scaled_flows(flows, np.array([5.0, 60.0]), ("old", "young"))
    assert scaled[0].tolist() == [5.0, 0.0, 0.0] and scaled[1].tolist() == [10.0, 20.0, 30.0]
    assert any("old" in n and "period 1" in n for n in notes)


def test_a_negative_selected_unpaid_is_discounted_like_any_cash_flow_and_flagged() -> None:
    flows = np.array([[10.0, 10.0]])
    scaled, notes = _scaled_flows(flows, np.array([-8.0]), ("A",))
    assert scaled[0].tolist() == [-4.0, -4.0]
    assert any("negative selected unpaid" in n for n in notes)
    present = (scaled[0] * flat_curve().discount_factors(np.array([0.5, 1.5]))).sum()
    assert present == pytest.approx(-4 / 1.1**0.5 - 4 / 1.1**1.5, rel=1e-14)


def test_the_tail_amount_is_spread_evenly_over_the_tail_payment_years() -> None:
    chain = fitted(tail_factor=1.2)
    flows, weights, notes = _pattern(chain, None, tail_periods=5)
    assert weights.tolist() == [0.2] * 5 and "evenly over 5 periods" in notes[0]
    i = 3  # three more development columns, then the tail from the fourth future period
    amount = chain.latest[i] * chain.cdf[0] * (1 - 1 / chain.cdf[3])
    assert amount > 0
    np.testing.assert_allclose(flows[i, 3:8], amount * 0.2, rtol=1e-12)
    np.testing.assert_allclose(flows.sum(axis=1), chain.reserve, rtol=1e-12, atol=1e-9)


def test_the_timing_of_a_cash_flow_changes_its_factor_in_the_order_start_middle_end() -> None:
    start, end = date(2025, 12, 31), date(2026, 12, 31)
    factors = []
    for timing in (Timing.START_OF_PERIOD, Timing.MID_PERIOD, Timing.END_OF_PERIOD):
        c = context(timing)
        factors.append(c.factors([c.payment_date(start, end)])[0])
    assert factors[0] > factors[1] > factors[2]
    assert factors[0] == pytest.approx(1.1 ** -((start - CUT_OFF).days / 365.25), rel=1e-13)
