"""Ground truth: it agrees with the simulated world and with itself."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.claims import END_OF_TIME
from actuarycanary.synthetic.days import to_day


def test_every_simulated_claim_is_counted_once_in_the_ultimates(baseline):
    ultimates = baseline.truth["ultimates"]
    assert ultimates["claims_simulated"].sum() == len(baseline.world)
    assert ultimates["claims_non_nil"].sum() == int((~baseline.world.c_nil).sum())


def test_ultimate_gross_is_the_sum_of_every_payment_including_those_after_the_cut_off(baseline):
    w = baseline.world
    assert baseline.truth["ultimates"]["ultimate_gross"].sum() == pytest.approx(
        w.p_amount.sum(), rel=1e-12
    )
    cut_off = to_day(baseline.scenario.meta.valuation.last)
    assert (w.p_day > cut_off).any()  # late payments exist and belong to the truth


def test_net_is_gross_minus_ceded(baseline):
    u = baseline.truth["ultimates"]
    assert (u["ultimate_net"] - (u["ultimate_gross"] - u["ultimate_ceded"])).abs().max() < 1e-6
    assert (u["ultimate_ceded"] <= u["ultimate_gross"] + 1e-6).all()
    assert u["ultimate_ceded"].sum() > 0
    base = u["ultimate_base_prices_try"] - u["ultimate_ceded_base_prices_try"]
    assert (u["ultimate_net_base_prices_try"] - base).abs().max() < 1e-6
    assert u["ultimate_ceded_base_prices_try"].sum() > 0


def test_ultimate_at_base_prices_is_the_sum_of_claim_costs(baseline):
    w = baseline.world
    expected = float(np.where(w.c_nil, 0.0, w.c_cost * w.c_fx_start).sum())
    assert baseline.truth["ultimates"]["ultimate_base_prices_try"].sum() == pytest.approx(
        expected, rel=1e-12
    )


def test_restating_to_cut_off_prices_matches_a_hand_calculation(baseline):
    """CV02: each payment times the index at the cut-off over the index at the payment date."""
    w, market = baseline.world, baseline.market
    cut_off = to_day(baseline.scenario.meta.valuation.last)
    claim = int(np.flatnonzero((w.c_line == "MOTOR_TPL") & ~w.c_nil)[0])
    mine = w.p_claim == claim
    restated = (
        w.p_amount[mine]
        * market.price_factor(np.array([cut_off]))
        / market.price_factor(w.p_day[mine])
    ).sum()
    line = baseline.truth["ultimates"].filter(pl.col("line") == "MOTOR_TPL")
    assert (
        line["ultimate_try_at_cutoff_prices"].sum() >= restated
    )  # the group holds this claim and others
    one = w.c_occ[claim]
    assert restated > 0 and one > 0


def test_a_truth_ibnr_is_the_ultimate_minus_what_is_known_at_the_cut_off(baseline):
    u = baseline.truth["ultimates"]
    assert (u["incurred_at_cutoff"] + u["ibnr_at_cutoff"] - u["ultimate_gross"]).abs().max() < 1e-6
    # at the last valuation the by-date table and the by-year table are the same quantity
    last = baseline.truth["ibnr_by_valuation"].filter(
        pl.col("valuation_date") == date(2025, 12, 31)
    )
    by_date = last.group_by("line", "accident_year").agg(pl.col("ibnr_true").sum())
    by_year = u.group_by("line", "accident_year").agg(pl.col("ibnr_at_cutoff").sum())
    joined = by_year.join(by_date, on=["line", "accident_year"], how="left").fill_null(0)
    assert joined["ibnr_true"].to_list() == pytest.approx(
        joined["ibnr_at_cutoff"].to_list(), abs=1e-3
    )


def test_true_ibnr_names_the_segment_of_each_line(baseline):
    table = baseline.truth["ibnr_by_valuation"]
    segments = table.group_by("line").agg(pl.col("segment").unique().alias("segment"))
    found = {row["line"]: row["segment"] for row in segments.iter_rows(named=True)}
    assert found == {
        "MOTOR_OD": ["NON_LIFE"],
        "MOTOR_TPL": ["NON_LIFE"],
        "PROPERTY": ["NON_LIFE"],
        "GROUP_TERM_LIFE": ["LIFE"],
    }


def test_the_ultimate_of_a_year_grows_with_its_occurrences_then_stays_fixed(baseline):
    table = baseline.truth["ibnr_by_valuation"].filter(
        (pl.col("line") == "MOTOR_OD") & (pl.col("accident_year") == 2023)
    )
    ordered = (
        table.group_by("valuation_date")
        .agg(pl.col("ultimate").sum(), pl.col("paid").sum())
        .sort("valuation_date")
    )
    ultimate = ordered["ultimate"].to_list()
    assert all(b >= a for a, b in zip(ultimate, ultimate[1:], strict=False))
    after = ordered.filter(pl.col("valuation_date") >= date(2023, 12, 31))["ultimate"]
    assert after.n_unique() == 1  # nothing more can occur in 2023
    assert (
        ordered.filter(pl.col("valuation_date") == date(2025, 12, 31))["paid"][0] <= after[0] + 1e-6
    )


def test_development_patterns_rise_to_one(baseline):
    pattern = baseline.truth["development_pattern"]
    rising, final = 0, []
    for _, group in pattern.group_by("line", "accident_year"):
        paid = group.sort("lag_years")["paid_share"].to_list()
        assert all(b >= a - 1e-12 for a, b in zip(paid, paid[1:], strict=False))
        assert group["reported_count_share"].max() == pytest.approx(1.0)
        final.append(paid[-1])
        rising += paid[0] < paid[-1] - 0.05
    assert rising > 0
    assert np.median(final) > 0.95  # a single huge claim can still be open after ten years


def test_the_pattern_marks_which_points_the_data_files_can_show(baseline):
    pattern = baseline.truth["development_pattern"]
    observed = pattern.filter(pl.col("observed_at_cutoff"))
    assert (observed["valuation_date"] <= date(2025, 12, 31)).all()
    assert (
        pattern.filter(~pl.col("observed_at_cutoff"))["valuation_date"] > date(2025, 12, 31)
    ).all()


def test_the_true_inflation_path_is_the_market_index(baseline):
    path = baseline.truth["inflation"]
    observed = path.filter(pl.col("observed_in_files"))
    assert observed.height == 120
    assert observed["cpi"].to_list() == pytest.approx(baseline.market.cpi[:120].tolist())
    assert (
        path["claims_index_MOTOR_TPL"][-1] > path["claims_index_MOTOR_OD"][-1]
    )  # higher superimposed inflation
    assert (path["claims_index_GROUP_TERM_LIFE"] == 1.0).all()  # death benefits are fixed amounts


def test_expected_frequency_is_the_parameter(baseline):
    table = baseline.truth["frequency_severity"]
    line = table.filter(pl.col("line") == "MOTOR_OD")
    assert (line["expected_frequency"] == 0.22).all()
    assert (
        table.filter(pl.col("line") == "GROUP_TERM_LIFE")["expected_base_severity_try"].null_count()
        == 4
    )


def test_ultimates_cover_every_line_entity_and_year_that_earned_premium(baseline):
    u = baseline.truth["ultimates"]
    assert set(u["line"]) == set(baseline.scenario.lines)
    assert set(u["accident_year"]) == {2022, 2023, 2024, 2025}
    assert (u["earned_premium"] > 0).all()
    assert u["ultimate_loss_ratio"].drop_nulls().min() >= 0


def test_unreported_claims_are_in_the_truth_but_not_in_the_files(baseline):
    w = baseline.world
    cut_off = to_day(baseline.scenario.meta.valuation.last)
    hidden = int((w.c_rep > cut_off).sum())
    assert hidden > 0
    assert baseline.clean["claims"].height == len(w) - hidden
    final = w.state(np.arange(len(w)), np.full(len(w), END_OF_TIME))
    assert (final["status"] != -1).all()
