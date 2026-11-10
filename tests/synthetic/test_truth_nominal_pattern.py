"""The truth files agree on their basis: the nominal development pattern reproduces the unpaid
share of ultimates.csv, and the inflation-free pattern is the one without inflation (0371)."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.build import simulate
from tests.synthetic.conftest import simulate_with

CUT_OFF_YEAR = 2025
TOLERANCE = 1e-9  # both files are sums of the same payments; only float order differs


def _unpaid_share_in_ultimates(sim, line: str, accident_year: int) -> float:
    rows = sim.truth["ultimates"].filter(
        (pl.col("line") == line) & (pl.col("accident_year") == accident_year)
    )
    assert set(rows["currency"]) == {"TRY"}  # one currency, so the amounts add up
    return 1.0 - rows["paid_at_cutoff"].sum() / rows["ultimate_gross"].sum()


def _check_unpaid_share_agrees(sim, line: str) -> int:
    pattern = sim.truth["development_pattern"].filter(
        (pl.col("line") == line) & (pl.col("valuation_date") == date(CUT_OFF_YEAR, 12, 31))
    )
    assert pattern.height > 0
    for row in pattern.iter_rows(named=True):
        from_ultimates = _unpaid_share_in_ultimates(sim, line, row["accident_year"])
        assert 1.0 - row["paid_share_nominal"] == pytest.approx(from_ultimates, abs=TOLERANCE)
    return pattern.height


def test_motor_tpl_unpaid_share_of_ultimates_is_one_minus_the_nominal_pattern(baseline):
    assert _check_unpaid_share_agrees(baseline, "MOTOR_TPL") >= 3


def test_every_try_line_agrees_not_only_motor_tpl(baseline):
    for line in ("MOTOR_OD", "MOTOR_TPL", "GROUP_TERM_LIFE"):
        assert _check_unpaid_share_agrees(baseline, line) >= 3


def test_nominal_shares_rise_and_start_below_the_inflation_free_ones(baseline):
    pattern = baseline.truth["development_pattern"]
    for _, group in pattern.group_by("line", "accident_year"):
        ordered = group.sort("lag_years")
        paid = ordered["paid_share_nominal"].to_list()
        assert all(b >= a - 1e-12 for a, b in zip(paid, paid[1:], strict=False))
        assert 0.0 <= paid[0] <= 1.0 + 1e-12
        # prices rise, so the late payments weigh more in the nominal ultimate: at every lag the
        # nominal paid share is not above the inflation-free one (positive inflation, one currency)
        if group["line"][0] != "PROPERTY":
            assert (ordered["paid_share_nominal"] <= ordered["paid_share"] + 1e-9).all()


def test_without_inflation_the_two_bases_are_the_same_pattern():
    sim = simulate_with(
        {
            "market": {
                "cpi": {
                    "annual_rate_by_year": dict.fromkeys(range(2016, 2026), 0.0),
                    "monthly_noise_sd": 0.0,
                }
            },
            "lines": {
                "MOTOR_TPL": {"severity": {"superimposed_inflation": 0.0}},
            },
        }
    )
    pattern = sim.truth["development_pattern"].filter(pl.col("line") == "MOTOR_TPL")
    assert pattern.height > 0
    assert np.allclose(pattern["paid_share_nominal"], pattern["paid_share"], atol=1e-6)


@pytest.mark.slow
def test_motor_tpl_medium_unpaid_share_agrees_after_ten_years():
    """Written, not run in the item: baseline medium, accident year 2016 (0371)."""
    sim = simulate("baseline", "medium")
    row = sim.truth["development_pattern"].filter(
        (pl.col("line") == "MOTOR_TPL")
        & (pl.col("accident_year") == 2016)
        & (pl.col("lag_years") == 10)
    )
    from_ultimates = _unpaid_share_in_ultimates(sim, "MOTOR_TPL", 2016)
    assert 1.0 - row["paid_share_nominal"][0] == pytest.approx(from_ultimates, abs=TOLERANCE)
    assert from_ultimates > 0.2  # 28 per cent in prices of the day, the late payments weigh most
    assert 1.0 - row["paid_share"][0] < 0.03  # 1.9 per cent in base-date prices
