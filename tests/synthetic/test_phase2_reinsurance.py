"""The treaty table and the ceded movements: the rule that ties them to claim_valuations.

Rule (record 0240): the ceded paid and the ceded case reserve of a claim in claim_valuations, at
every valuation date, equal the sum of its CEDED_CLAIM_PAID and CEDED_CASE_RESERVE movements booked
on or before that date, to the cent; the movements are the treaty application of the simulation,
split by treaty. Premium movements are the ceded rows of the premiums feed, added up by treaty,
booking month, currency and line.
"""

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.reinsurance import surplus_policy_share

TREATIES = "reinsurance_treaties"
MOVES = "reinsurance_transactions"


@pytest.fixture(params=["clean_baseline", "heavy"])
def sim(request):
    """The baseline and the heavy programme, one after the other."""
    return request.getfixturevalue(request.param)


def _frame(sim, feed):
    return sim.phase2.frames[feed][feed]


def test_ceded_fields_of_the_valuations_are_the_accumulated_movements(sim):
    moves, v = _frame(sim, MOVES), sim.clean["claim_valuations"]
    v = v.sort(["claim_id", "valuation_date"])
    for kind, column in (
        ("CEDED_CLAIM_PAID", "ceded_paid_to_date"),
        ("CEDED_CASE_RESERVE", "ceded_reserve"),
    ):
        steps = (
            moves.filter(pl.col("type") == kind)
            .group_by(["claim_id", "booking_date"])
            .agg(pl.col("amount").sum())
            .rename({"booking_date": "valuation_date"})
        )
        # the movements are booked on valuation dates of their claim, so a join finds them all
        joined = v.join(steps, on=["claim_id", "valuation_date"], how="left")
        assert joined["amount"].is_not_null().sum() == steps.height
        joined = joined.with_columns(
            pl.col("amount").fill_null(0.0).cum_sum().over("claim_id").alias("cumulative")
        )
        assert (joined["cumulative"] - joined[column]).abs().max() < 0.005


def test_movements_are_booked_at_month_ends_on_known_claims_and_treaties(heavy):
    moves, treaties = _frame(heavy, MOVES), _frame(heavy, TREATIES)
    assert set(moves["treaty_id"]) <= set(treaties["treaty_id"])
    assert (moves["booking_date"].dt.offset_by("1d").dt.day() == 1).all()
    claim_ids = set(heavy.clean["claims"]["claim_id"])
    booked = moves.filter(pl.col("claim_id").is_not_null())
    assert set(booked["claim_id"]) <= claim_ids
    assert moves["transaction_id"].n_unique() == moves.height
    # an event treaty names the event of the claim
    cat = booked.filter(pl.col("treaty_id") == "XL_PROPERTY_CAT")
    assert cat.height == cat.filter(pl.col("event_code").is_not_null()).height


def test_premium_movements_are_the_ceded_rows_of_the_premiums_feed(sim):
    premiums = sim.clean["premiums"].join(
        sim.clean["policies"].select("policy_id", "line"), on="policy_id"
    )
    ceded = premiums.filter(pl.col("type").is_in(["CEDED_PREMIUM", "RI_COMMISSION"]))
    side = (
        ceded.with_columns(pl.col("booking_date").dt.month_end().alias("month"))
        .group_by(["type", "month", "line", "currency"])
        .agg(pl.col("amount").sum().alias("premiums"))
    )
    moves = _frame(sim, MOVES).filter(pl.col("type").is_in(["CEDED_PREMIUM", "RI_COMMISSION"]))
    other = (
        moves.with_columns(pl.col("booking_date").dt.month_end().alias("month"))
        .group_by(["type", "month", "line", "currency"])
        .agg(pl.col("amount").sum().alias("movements"))
    )
    both = side.join(other, on=["type", "month", "line", "currency"], how="full", coalesce=True)
    both = both.fill_null(0.0)
    assert both.height > 0
    assert (both["premiums"] - both["movements"]).abs().max() < 0.005
    assert moves["claim_id"].null_count() == moves.height  # treaty level, no claim


def test_the_treaty_table_has_a_row_per_contract_year_and_line(clean_baseline):
    t = _frame(clean_baseline, TREATIES)
    assert t.height == t.select("treaty_id", "inception_date", "line").n_unique()
    assert set(t["treaty_type"]) == {"QUOTA_SHARE", "EXCESS_OF_LOSS"}
    # contract years follow each other without gaps and cover the simulated years
    for _, group in t.group_by(["treaty_id", "line"]):
        starts = group.sort("inception_date")
        assert (starts["expiry_date"][:-1] == starts["inception_date"][1:]).all()
    assert t["inception_date"].min().year <= 2022 and t["expiry_date"].max().year >= 2025
    assert set(t["attachment_basis"]) == {"LOSSES_OCCURRING"}


def test_layers_surplus_and_event_cover_are_in_the_table(heavy):
    t = _frame(heavy, TREATIES)
    assert {"QUOTA_SHARE", "SURPLUS", "EXCESS_OF_LOSS"} <= set(t["treaty_type"])
    one_year = t.filter(pl.col("inception_date").dt.year() == 2024)
    layers = one_year.filter(pl.col("treaty_id").str.starts_with("XL_TPL")).sort("retention")
    assert layers["treaty_id"].to_list() == ["XL_TPL_L1", "XL_TPL_L2", "XL_TPL_L3"]
    assert (layers["retention"][1:] > layers["retention"][:-1]).all()
    surplus = one_year.filter(pl.col("treaty_type") == "SURPLUS")
    assert surplus["number_of_lines"][0] == 9 and surplus["retention"][0] > 800_000
    event = one_year.filter(pl.col("treaty_id") == "XL_PROPERTY_CAT")
    assert event["loss_basis"][0] == "EVENT"
    assert set(layers["index_series"]) == {"CPI_TR"}
    # the retention is written at the price level of the inception date, so it rises with prices
    first = t.filter(pl.col("treaty_id") == "XL_TPL_L1").sort("inception_date")
    assert first["retention"][-1] > first["retention"][0]


def test_net_is_gross_less_ceded_per_treaty_and_the_parts_add_up_per_claim(sim):
    by_treaty = sim.phase2.truth["reinsurance_by_treaty"]
    gap = (
        by_treaty["gross_ultimate_covered"]
        - by_treaty["ceded_ultimate"]
        - by_treaty["net_ultimate_after_treaty"]
    )
    assert gap.abs().max() < 0.02
    by_claim = sim.phase2.truth["reinsurance_by_claim"]
    assert (by_claim["ceded_ultimate"] > 0).all()
    assert (
        by_claim["gross_ultimate"]
        - by_claim["ceded_ultimate"]
        - by_claim["net_ultimate_after_treaty"]
    ).abs().max() < 0.02
    # the parts add up to the ceded ultimate of the earlier truth, per line and currency
    world = sim.world
    line_of = dict(
        zip(
            [f"{i + 1:08d}" for i in range(len(world))],
            world.c_line.tolist(),
            strict=True,
        )
    )
    mine = (
        by_claim.with_columns(
            pl.col("claim_id").replace_strict(line_of).alias("line"),
        )
        .group_by(["line", "currency"])
        .agg(pl.col("ceded_ultimate").sum())
        .sort(["line", "currency"])
    )
    earlier = (
        sim.truth["ultimates"]
        .group_by(["line", "currency"])
        .agg(pl.col("ultimate_ceded").sum().alias("earlier"))
        .sort(["line", "currency"])
    )
    both = mine.join(earlier, on=["line", "currency"], how="full", coalesce=True).fill_null(0.0)
    assert (both["ceded_ultimate"] - both["earlier"]).abs().max() < 0.05


def test_the_heavy_programme_is_hit_in_every_layer(heavy):
    hit = (
        heavy.phase2.truth["reinsurance_by_treaty"]
        .group_by("treaty_id")
        .agg(pl.col("claims_ceded").sum())
    )
    claims = dict(zip(hit["treaty_id"], hit["claims_ceded"], strict=True))
    for treaty in (
        "QS_MOTOR_OD",
        "QS_PROPERTY",
        "SURPLUS_PROPERTY",
        "XL_TPL_L1",
        "XL_TPL_L2",
        "XL_TPL_L3",
    ):
        assert claims[treaty] > 0, treaty
    cession = heavy.phase2.truth["reinsurance_by_treaty"]
    total_gross = sum(heavy.truth["ultimates"]["ultimate_gross"].to_list())
    assert cession["ceded_ultimate"].sum() > 0.2 * total_gross


def test_surplus_shares_follow_the_sum_insured(heavy):
    surplus = heavy.scenario.phase2.surplus[0]
    share = surplus_policy_share(heavy.policies, heavy.world.market, surplus)
    assert share.min() >= 0.0 and share.max() < 1.0
    covered = np.isin(heavy.policies.line, surplus.lines)
    assert (share[~covered] >= 0).all()
    insured = heavy.policies.sum_insured * heavy.policies.units
    line = surplus.retained_line * heavy.world.market.price_factor(heavy.policies.start)
    small = covered & (insured < line) & (heavy.policies.currency == "TRY")
    assert small.any() and (share[small] == 0.0).all()
    large = covered & (insured > 2 * line) & (insured < 8 * line)
    large &= heavy.policies.currency == "TRY"
    assert large.any() and ((share[large] >= 0.5) & (share[large] <= 0.875)).all()
    assert (share[covered] > 0).any()


def test_a_scenario_without_surplus_has_the_same_claim_data_as_one_with_it(clean_baseline, heavy):
    """Only what is ceded differs: the gross world is the baseline's."""
    assert heavy.clean["claims"].equals(clean_baseline.clean["claims"])
    assert heavy.clean["policies"].equals(clean_baseline.clean["policies"])
    gross = ["claim_id", "valuation_date", "paid_to_date", "case_reserve", "status"]
    assert (
        heavy.clean["claim_valuations"]
        .select(gross)
        .equals(clean_baseline.clean["claim_valuations"].select(gross))
    )
    assert not heavy.clean["claim_valuations"]["ceded_paid_to_date"].equals(
        clean_baseline.clean["claim_valuations"]["ceded_paid_to_date"]
    )
