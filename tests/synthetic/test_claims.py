"""The claim simulation, and what the clean (fault-free) valuations promise.

Rules proved here are the data rules of spec/data/claim_valuations.yaml and claims.yaml
(DV-CLV-xx, DV-CLM-xx) on the simulated data before any fault is injected.
"""

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.claims import CATASTROPHE
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.portfolio import NO_DAY
from tests.synthetic.conftest import simulate_with


@pytest.fixture(scope="module")
def clean(baseline) -> pl.DataFrame:
    return baseline.clean["claim_valuations"]


def test_dv_clv_05_every_valuation_is_a_month_end(clean):
    assert (clean["valuation_date"].dt.month_end() == clean["valuation_date"]).all()


def test_dv_clv_06_one_row_per_claim_and_month(clean):
    assert clean.select("claim_id", "valuation_date").is_unique().all()


def test_dv_clv_07_paid_never_decreases(clean):
    steps = clean.sort("claim_id", "valuation_date").select(
        pl.col("paid_to_date").diff().over("claim_id")
    )
    assert (steps.to_series().drop_nulls() >= 0).all()


def test_dv_clv_08_amounts_are_not_negative(clean):
    amounts = [c for c in clean.columns if c.endswith("_to_date") or c.endswith("_reserve")]
    assert all((clean[c] >= 0).all() for c in amounts)


def test_dv_clv_09_dv_clv_10_closed_claims_have_no_reserve_and_nil_closures_no_payment(clean):
    closed = clean.filter(pl.col("status").is_in(["CLOSED", "CLOSED_NIL"]))
    assert closed.height > 0 and (closed["case_reserve"] == 0).all()
    nil = clean.filter(pl.col("status") == "CLOSED_NIL")
    assert nil.height > 0 and (nil["paid_to_date"] == 0).all()


def test_dv_clv_11_ceded_amounts_never_exceed_gross(clean):
    assert (clean["ceded_paid_to_date"] <= clean["paid_to_date"]).all()
    assert (clean["ceded_reserve"] <= clean["case_reserve"]).all()


def test_dv_clv_12_a_claim_keeps_its_currency(clean):
    assert (
        clean.group_by("claim_id")
        .agg(pl.col("currency").n_unique())
        .filter(pl.col("currency") > 1)
        .is_empty()
    )


def test_dv_clv_13_no_month_is_missing_between_first_and_last_valuation(clean):
    months = clean.with_columns(
        (pl.col("valuation_date").dt.year() * 12 + pl.col("valuation_date").dt.month()).alias("m")
    )
    spans = months.group_by("claim_id").agg(
        (pl.col("m").max() - pl.col("m").min() + 1 - pl.len()).alias("gap")
    )
    assert (spans["gap"] == 0).all()


def test_dv_clv_14_every_valued_claim_has_a_header(baseline, clean):
    assert set(clean["claim_id"]) <= set(baseline.clean["claims"]["claim_id"])


def test_dv_clm_04_dv_clm_05_dv_clm_10_dates_in_a_claim_header_are_consistent(baseline):
    claims = baseline.clean["claims"]
    assert (claims["occurrence_date"] <= claims["report_date"]).all()
    assert (
        claims.filter(pl.col("close_date").is_not_null())["report_date"]
        <= claims.filter(pl.col("close_date").is_not_null())["close_date"]
    ).all()
    world = baseline.world
    reported = world.c_rep <= to_day(baseline.scenario.meta.valuation.last)
    p = baseline.policies
    pol = world.c_policy[reported]
    stop = np.minimum(p.end[pol], p.cancel[pol])
    assert ((world.c_occ[reported] >= p.start[pol]) & (world.c_occ[reported] < stop)).all()


def test_the_timeline_of_every_claim_is_ordered(baseline):
    w = baseline.world
    assert (w.c_occ <= w.c_rep).all() and (w.c_rep < w.c_e0).all()
    reopened = w.has_reopen
    assert reopened.any()
    assert (w.c_e0[reopened] < w.c_s1[reopened]).all() and (
        w.c_s1[reopened] < w.c_e1[reopened]
    ).all()
    assert (w.c_s1[~reopened] == NO_DAY).all()
    assert ((w.p_day >= w.c_rep[w.p_claim]) & (w.p_day <= w.last_event[w.p_claim])).all()


def test_payment_shares_of_every_claim_add_up_to_its_cost(baseline):
    w = baseline.world
    totals = np.bincount(w.p_claim, weights=w.p_w, minlength=len(w))
    assert totals == pytest.approx(np.ones(len(w)), abs=1e-9)


def test_a_snapshot_is_the_sum_of_the_payments_made_by_then(baseline, clean):
    w = baseline.world
    ids = clean["claim_id"].to_numpy()
    days = clean["valuation_date"].to_numpy().astype("datetime64[D]").astype(np.int64)
    for i in range(0, clean.height, 37):
        claim = int(ids[i]) - 1
        made = (w.p_claim == claim) & (w.p_day <= days[i])
        assert clean["paid_to_date"][i] == pytest.approx(w.p_amount[made].sum(), abs=0.011)
        spent = (w.p_claim == claim) & (w.p_day <= days[i])
        assert clean["expense_allocated_to_date"][i] == pytest.approx(
            w.p_expense[spent].sum(), abs=0.011
        )


def test_a_payment_is_the_claim_cost_times_its_share_times_the_inflation_index(baseline):
    w = baseline.world
    live = ~w.c_nil[w.p_claim]
    expected = w.c_cost[w.p_claim] * w.p_w * w.index_for(w.p_claim, w.p_day)
    assert w.p_amount[live] == pytest.approx(expected[live], abs=0.011)
    assert (w.p_amount[~live] == 0).all()


def test_open_claims_carry_a_reserve_and_it_falls_to_zero_when_the_claim_closes(baseline):
    w = baseline.world
    claim = np.arange(len(w))
    open_day = w.c_rep + 0  # the day of reporting
    open_state = w.state(claim, open_day)
    assert (open_state["reserve"] > 0).mean() > 0.95
    after = w.state(claim, np.where(w.has_reopen, w.c_s1 - 1, w.c_e0))
    assert (after["reserve"] == 0).all()


def test_recoveries_arrive_after_the_last_payment_and_never_exceed_what_was_paid(baseline):
    w = baseline.world
    assert len(w.v_claim) > 0
    assert (w.v_day > w.last_event[w.v_claim]).all()
    final = w.ultimate()
    assert ((final["subrogation"] + final["salvage"]) <= final["paid"] * 1.0000001 + 0.02).all()


def test_only_the_line_with_litigation_has_litigated_claims(baseline):
    w = baseline.world
    assert w.c_litigated.any()
    assert set(w.c_line[w.c_litigated]) == {"MOTOR_TPL"}


def test_catastrophe_claims_share_the_event_date_and_code(baseline):
    w = baseline.world
    cat = w.c_kind == CATASTROPHE
    assert cat.sum() >= 1
    for event, code in enumerate(w.event_codes):
        members = w.c_event == event
        assert (w.c_occ[members] == w.event_dates[event]).all()
        header = baseline.clean["claims"].filter(pl.col("event_code") == code)
        assert header.height == int(
            (members & (w.c_rep <= to_day(baseline.scenario.meta.valuation.last))).sum()
        )


def test_a_foreign_currency_claim_is_in_its_own_currency():
    sim = simulate_with({"lines": {"PROPERTY": {"portfolio": {"foreign_currency_share": 1.0}}}})
    w = sim.world
    prop = w.c_line == "PROPERTY"
    assert prop.any() and set(w.c_currency[prop]) <= {"USD", "EUR"}
    # cost at base-date prices is in foreign units: it is the lira cost divided by the starting rate
    assert (w.c_fx_start[prop] > 1).all()
    clean = sim.clean["claim_valuations"]
    property_ids = sim.clean["claims"].filter(pl.col("line") == "PROPERTY")["claim_id"]
    rows = clean.filter(pl.col("claim_id").is_in(property_ids.implode()))
    assert rows.height > 0 and set(rows["currency"]) <= {"USD", "EUR"}


def test_property_claims_are_capped_at_the_sum_insured_when_asked(baseline):
    w = baseline.world
    p = baseline.policies
    prop = (w.c_line == "PROPERTY") & (w.c_kind == 0)
    cost_now = w.c_cost * w.index_for(np.arange(len(w)), w.c_occ)
    assert (
        cost_now[prop] <= p.sum_insured[w.c_policy[prop]] * p.units[w.c_policy[prop]] * (1 + 1e-9)
    ).all()


def test_a_claim_has_a_close_date_exactly_when_its_last_valuation_is_closed(baseline, clean):
    last = clean.sort("valuation_date").group_by("claim_id").last().select("claim_id", "status")
    joined = baseline.clean["claims"].join(last, on="claim_id")
    closed = joined["status"].is_in(["CLOSED", "CLOSED_NIL"])
    assert joined.height == baseline.clean["claims"].height
    assert (joined["close_date"].is_not_null() == closed).all()
    assert closed.any() and (~closed).any()
