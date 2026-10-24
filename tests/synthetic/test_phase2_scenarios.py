"""The scenarios of the later feeds, their size and the way they leave the first six feeds alone."""

import pytest

from actuarycanary.synthetic.phase2 import PHASE2_FEEDS, TRUTH_USERS
from actuarycanary.synthetic.scenario import list_scenarios, load_scenario
from tests.synthetic.conftest import NO_FAULTS, simulate_named

FIRST_SIX = ("claim_valuations", "claims", "policies", "premiums", "expenses", "market")

NOT_MONEY = {
    "interest_rates_truth": "curve_id date tenor_months rate expected_inflation real_rate "
    "term_premium shock",
    "reinsurance_by_claim": "claim_id treaty_id currency",
    "reinsurance_by_treaty": "treaty_id line contract_year currency claims_covered claims_ceded",
    "recoveries_truth": "claim_id type recovery_date currency counterparty_type "
    "days_after_last_payment booked_by_cutoff",
    "ledger_gaps": "entity account_class period cause",
    "ledger_differences": "kind entity account period cause",
    "severity_truth": "line body_dist body_sigma body_cv tail_probability tail_alpha tail_xi "
    "tail_start_probability litigation_probability litigation_multiplier superimposed_inflation",
    "severity_tail_truth": "line probability_level",
    "life_contracts": "contract_id product entry_date entry_age sex first_exit_date "
    "first_exit_type exit_date exit_type reinstated reinstatement_date death_report_date in_data",
    "life_mortality_truth": "product sex age multiplier reference_force true_force true_q",
    "life_lapse_truth": "product policy_year decrement reference_rate lapse_multiplier "
    "true_rate true_force",
    "life_expected_decrements": "calendar_year product age policy_year exposure_years "
    "expected_deaths expected_lapses deaths deaths_reported lapses",
}


@pytest.fixture(scope="module")
def tiny_sims():
    """The four scenarios at tiny size, with their injected faults."""
    return {
        name: simulate_named(name)
        for name in ("baseline", "reinsurance_heavy", "life_book", "messy_headers")
    }


@pytest.fixture(scope="module")
def changed():
    """The baseline without faults, with other parameters for rates and the ledger."""
    return simulate_named(
        "baseline",
        {
            **NO_FAULTS,
            "phase2": {
                "rates": {"real_rate": 0.05},
                "ledger": {"other_income_share_of_written": 0.1},
            },
        },
    )


def _frames(sim, feed):
    return sim.frames[feed][feed]


def test_the_new_scenarios_are_listed_and_valid():
    names = list_scenarios()
    assert {"reinsurance_heavy", "life_book"} <= set(names)
    heavy = load_scenario("reinsurance_heavy")
    assert len(heavy.reinsurance) == 7 and heavy.phase2.surplus[0].treaty_id == "SURPLUS_PROPERTY"
    book = load_scenario("life_book").phase2.life_book
    assert book.enabled and {p.policy_type for p in book.products} == {"INDIVIDUAL", "GROUP"}
    group = [p for p in book.products if p.policy_type == "GROUP"]
    assert group and group[0].line == "GROUP_TERM_LIFE"
    assert load_scenario("messy_headers").phase2.life_book.enabled
    assert not load_scenario("baseline").phase2.life_book.enabled


@pytest.mark.parametrize("name", ["baseline", "reinsurance_heavy", "life_book", "messy_headers"])
def test_tiny_stays_under_two_thousand_rows_per_later_feed(name, tiny_sims):
    sim = tiny_sims[name]
    for feed in PHASE2_FEEDS:
        if feed in sim.frames:
            assert _frames(sim, feed).height < 2000, (name, feed)


def test_every_scenario_has_the_non_life_later_feeds_and_only_the_life_book_the_life_ones(
    tiny_sims,
):
    for name in ("baseline", "reinsurance_heavy"):
        sim = tiny_sims[name]
        assert set(sim.phase2.frames) == {
            "interest_rates",
            "reinsurance_treaties",
            "reinsurance_transactions",
            "recoveries",
            "ledger",
        }
    for name in ("life_book", "messy_headers"):
        assert {"life_in_force", "life_events", "fund_flows"} <= set(tiny_sims[name].phase2.frames)


def test_the_life_book_leaves_the_first_six_feeds_as_they_are(clean_baseline, life):
    for feed in FIRST_SIX:
        for key, frame in clean_baseline.frames[feed].items():
            assert life.frames[feed][key].equals(frame), feed
    for name, table in clean_baseline.truth.items():
        assert life.truth[name].equals(table), name


def test_a_parameter_of_a_later_feed_moves_none_of_the_first_six(clean_baseline, changed):
    for feed in FIRST_SIX:
        for key, frame in clean_baseline.frames[feed].items():
            assert changed.frames[feed][key].equals(frame), feed
    assert not changed.phase2.frames["interest_rates"]["interest_rates"].equals(
        clean_baseline.phase2.frames["interest_rates"]["interest_rates"]
    )
    assert changed.phase2.frames["recoveries"]["recoveries"].equals(
        clean_baseline.phase2.frames["recoveries"]["recoveries"]
    )


def test_every_truth_column_is_money_with_a_currency_or_not_money(life):
    assert set(life.phase2.truth) == set(NOT_MONEY) | set()
    assert set(TRUTH_USERS) == set(life.phase2.truth)
    for name, table in life.phase2.truth.items():
        money = life.phase2.money.get(name, {})
        assert set(table.columns) == set(money) | set(NOT_MONEY[name].split()), name
        for column, (basis, _) in money.items():
            assert basis in ("row", "reporting"), (name, column)
            if basis == "row":
                assert "currency" in table.columns, name
