"""Recoveries, the trial balance and the interest-rate curves."""

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.days import month_index, to_day
from actuarycanary.synthetic.ledger import chart, mapped_amounts, period_rates
from tests.synthetic.conftest import NO_FAULTS, simulate_named

NO_DIFFERENCES = {
    "phase2": {
        "ledger": {
            "differences": {
                "premium_timing_months": 0,
                "unmapped_account": False,
                "outstanding_with_ibnr_share": 0.0,
                "translation_months": 0,
                "missing_months": 0,
            }
        }
    }
}


@pytest.fixture(scope="module")
def balanced():
    """The baseline with no fault and no reconciliation difference in the ledger."""
    return simulate_named("baseline", {**NO_FAULTS, **NO_DIFFERENCES})


def _feed(sim, name):
    return sim.phase2.frames[name][name]


# --- recoveries ----------------------------------------------------------------------------


def test_recoveries_add_up_to_the_to_date_fields_at_every_valuation(clean_baseline):
    r = _feed(clean_baseline, "recoveries")
    v = clean_baseline.clean["claim_valuations"].sort(["claim_id", "valuation_date"])
    for kind, column in (
        ("RECOVERY_SUBROGATION", "subrogation_to_date"),
        ("RECOVERY_SALVAGE", "salvage_to_date"),
    ):
        steps = (
            r.filter(pl.col("type") == kind)
            .group_by(["claim_id", "booking_date"])
            .agg(pl.col("amount").sum())
            .rename({"booking_date": "valuation_date"})
            .sort(["claim_id", "valuation_date"])
        )
        # a recovery is received on any day; the field shows it at the next month end
        steps = steps.with_columns(pl.col("valuation_date").dt.month_end())
        steps = steps.group_by(["claim_id", "valuation_date"]).agg(pl.col("amount").sum())
        joined = v.join(steps, on=["claim_id", "valuation_date"], how="left")
        assert joined["amount"].is_not_null().sum() == steps.height
        joined = joined.with_columns(
            pl.col("amount").fill_null(0.0).cum_sum().over("claim_id").alias("cumulative")
        )
        assert (joined["cumulative"] - joined[column]).abs().max() < 0.005


def test_recoveries_after_the_cut_off_are_in_the_truth_only(clean_baseline):
    feed = _feed(clean_baseline, "recoveries")
    truth = clean_baseline.phase2.truth["recoveries_truth"]
    cut_off = clean_baseline.scenario.meta.valuation.last
    assert feed["booking_date"].max() <= cut_off
    late = truth.filter(~pl.col("booked_by_cutoff"))
    assert late.height > 0 and late["recovery_date"].min() > cut_off
    assert truth.filter(pl.col("booked_by_cutoff")).height == feed.height
    assert (feed["amount"] > 0).all() and feed["transaction_id"].n_unique() == feed.height
    assert set(feed["type"]) <= {"RECOVERY_SUBROGATION", "RECOVERY_SALVAGE"}
    assert set(feed["counterparty_type"]) <= {"INSURER", "OTHER_PARTY", "SALVAGE_BUYER"}
    assert feed.group_by(["claim_id", "type"]).len()["len"].max() == 1


def test_a_recovery_follows_the_last_payment_of_its_claim(clean_baseline):
    truth = clean_baseline.phase2.truth["recoveries_truth"]
    assert (truth["days_after_last_payment"] > 0).all()


# --- ledger ----------------------------------------------------------------------------------


def test_the_books_balance_and_the_balances_chain(clean_baseline):
    g = _feed(clean_baseline, "ledger")
    totals = g.group_by(["entity", "period"]).agg(pl.col("closing_balance").sum().alias("total"))
    # one month of one account row is left out on purpose, and the books are out by its balance
    out_of_balance = totals.filter(pl.col("total").abs() > 0.05)
    differences = clean_baseline.phase2.truth["ledger_differences"]
    missing = differences.filter(pl.col("kind") == "missing_row")
    assert out_of_balance.height == missing.height
    full = g.filter(pl.col("opening_balance").is_not_null() & pl.col("debit").is_not_null())
    assert (
        full["closing_balance"] - full["opening_balance"] - full["debit"] + full["credit"]
    ).abs().max() < 0.011
    assert (g["debit"] >= 0).all() and (g["credit"] >= 0).all()


def test_a_balanced_ledger_has_no_books_out_of_balance_and_years_roll_over(balanced):
    g = _feed(balanced, "ledger")
    totals = g.group_by(["entity", "period"]).agg(pl.col("closing_balance").sum())
    assert totals["closing_balance"].abs().max() < 0.05
    income = {a.code for a in chart() if a.kind == "PL"}
    january = g.filter(pl.col("account").is_in(list(income)) & (pl.col("period").dt.month() == 1))
    assert (january["opening_balance"] == 0).all()
    december = g.filter(pl.col("period").dt.month() == 12)
    assert december.filter(pl.col("account").is_in(list(income)))["closing_balance"].abs().max() > 0
    # the result of 2022 is in the account of earlier years from January 2023 on
    earlier = g.filter((pl.col("account") == "590") & (pl.col("period").dt.year() == 2023))
    assert earlier.height > 0 and earlier["closing_balance"].abs().max() > 0


def test_without_differences_the_ledger_equals_the_platform_in_every_class(balanced):
    gaps = balanced.phase2.truth["ledger_gaps"]
    assert gaps.height > 0
    assert gaps["gap"].abs().max() < 0.005
    assert balanced.phase2.truth["ledger_differences"].height == 0
    assert set(gaps["account_class"]) == {
        "PREMIUM",
        "CLAIMS_PAID",
        "OUTSTANDING",
        "UPR",
        "COMMISSION",
        "EXPENSE",
        "RI",
    }


def test_the_ledger_equals_the_platform_measures_computed_from_the_feeds(balanced):
    """Premium, claims paid and outstanding from the feeds and the market file, not from the
    ledger code: flows at the average rate of the booking month, stocks at the month-end rate."""
    scenario = balanced.scenario
    sheets = balanced.frames["market"]["fx"]
    rate = (
        sheets.filter(pl.col("kind").is_in(["FX_PERIOD_AVERAGE", "FX_PERIOD_END"]))
        .with_columns(
            pl.col("series_id").str.slice(0, 3).alias("currency"),
            pl.col("date").dt.month_end().alias("month"),
        )
        .select("currency", "month", "kind", "value")
    )
    average = rate.filter(pl.col("kind") == "FX_PERIOD_AVERAGE").rename({"value": "avg"})
    end = rate.filter(pl.col("kind") == "FX_PERIOD_END").rename({"value": "end"})
    reporting = scenario.meta.reporting_currency

    def converted(frame: pl.DataFrame, column: str, kind: pl.DataFrame, name: str) -> pl.DataFrame:
        joined = frame.join(
            kind.select("currency", "month", name), on=["currency", "month"], how="left"
        )
        return joined.with_columns(
            pl.when(pl.col("currency") == reporting)
            .then(pl.col(column))
            .otherwise(pl.col(column) * pl.col(name))
            .alias("try")
        )

    policies = balanced.clean["policies"].select("policy_id", "entity")
    premiums = balanced.clean["premiums"].join(policies, on="policy_id")
    written = premiums.filter(
        pl.col("type").is_in(["WRITTEN", "ENDORSEMENT", "CANCELLATION", "REFUND"])
    ).with_columns(pl.col("booking_date").dt.month_end().alias("month"))
    written = converted(written, "amount", average, "avg")
    mine = written.group_by(["entity", "month"]).agg(pl.col("try").sum().round(2).alias("mine"))
    claims = balanced.clean["claims"].select("claim_id", "entity")
    v = balanced.clean["claim_valuations"].join(claims, on="claim_id")
    v = v.with_columns(pl.col("valuation_date").alias("month"))
    outstanding = converted(v, "case_reserve", end, "end")
    stock = outstanding.group_by(["entity", "month"]).agg(pl.col("try").sum().alias("mine"))

    gaps = balanced.phase2.truth["ledger_gaps"]

    def check(cls: str, mine_frame: pl.DataFrame) -> None:
        side = gaps.filter(pl.col("account_class") == cls).rename({"period": "month"})
        both = side.join(mine_frame, on=["entity", "month"], how="left").fill_null(0.0)
        assert both.height > 0
        assert (both["ledger_amount"] - both["mine"]).abs().max() < 0.011, cls

    check("PREMIUM", mine)
    check("OUTSTANDING", stock)


def test_every_difference_shows_in_the_gap_table_and_nothing_else_does(clean_baseline):
    differences = clean_baseline.phase2.truth["ledger_differences"]
    gaps = clean_baseline.phase2.truth["ledger_gaps"]
    assert set(differences["kind"]) == {
        "premium_timing",
        "translation",
        "ibnr_in_outstanding",
        "unmapped_account",
        "missing_row",
    }
    wrong = gaps.filter(pl.col("gap").abs() > 0.005)
    assert wrong["cause"].null_count() == 0
    assert set(wrong["cause"]) == {"premium_timing", "translation", "ibnr_in_outstanding"}
    # the gap is the platform's figure minus the ledger's: the difference with the other sign
    timing = differences.filter(pl.col("kind") == "premium_timing")
    for row in timing.iter_rows(named=True):
        gap = wrong.filter(
            (pl.col("entity") == row["entity"])
            & (pl.col("period") == row["period"])
            & (pl.col("account_class") == "PREMIUM")
        )["gap"].sum()
        assert abs(gap + row["ledger_minus_platform"]) < 0.01


def test_the_mapping_profile_leaves_the_suspense_account_out(clean_baseline):
    profile = clean_baseline.phase2.files["truth/ledger_mapping_profile.csv"]
    patterns = set(profile["account_pattern"])
    assert "297*" not in patterns and "600*" in patterns
    assert profile.filter(pl.col("account_pattern") == "600*")["sign"][0] == -1
    ledger = _feed(clean_baseline, "ledger")
    unmapped = ledger.filter(pl.col("account") == "297")
    assert unmapped.height > 0 and unmapped["account_class"].null_count() == unmapped.height
    mapped = mapped_amounts(ledger, profile, 1)
    assert "297" not in set(mapped["account_class"])


def test_period_rates_equal_the_market_file(clean_baseline):
    market = clean_baseline.world.market
    scenario = clean_baseline.scenario
    sheets = clean_baseline.frames["market"]["fx"].filter(pl.col("series_id") == "USD/TRY")
    first_month = int(month_index(to_day(scenario.meta.valuation.first)))
    average, end = period_rates(scenario, market, first_month, first_month + 11)
    written = sheets.filter(pl.col("kind") == "FX_PERIOD_AVERAGE").sort("date").head(12)
    assert np.allclose(average["USD"], written["value"].to_numpy(), atol=1e-9)
    written = sheets.filter(pl.col("kind") == "FX_PERIOD_END").sort("date").head(12)
    assert np.allclose(end["USD"], written["value"].to_numpy(), atol=1e-9)


# --- interest rates --------------------------------------------------------------------------


def test_curves_have_every_tenor_on_every_date_and_one_currency_each(clean_baseline):
    r = _feed(clean_baseline, "interest_rates")
    tenors = clean_baseline.scenario.phase2.rates.tenors_months
    per_date = r.group_by(["curve_id", "date"]).agg(pl.col("tenor_months").sort())
    assert all(t == sorted(tenors) for t in per_date["tenor_months"].to_list())
    assert r.group_by("curve_id").agg(pl.col("currency").n_unique())["currency"].max() == 1
    assert set(r["rate_type"]) == {"SPOT"} and set(r["compounding"]) == {"ANNUAL"}
    assert r.select("curve_id", "date", "tenor_months").n_unique() == r.height
    assert (r["date"].dt.offset_by("1d").dt.day() == 1).all()


def test_the_truth_splits_every_rate_into_its_parts(clean_baseline):
    t = clean_baseline.phase2.truth["interest_rates_truth"]
    parts = t["expected_inflation"] + t["real_rate"] + t["term_premium"] + t["shock"]
    assert (parts - t["rate"]).abs().max() < 2e-6


def test_the_try_curve_follows_the_inflation_path_of_the_scenario(clean_baseline):
    t = clean_baseline.phase2.truth["interest_rates_truth"].filter(
        (pl.col("curve_id") == "TRY_GOV") & (pl.col("tenor_months") == 12)
    )
    rates = clean_baseline.scenario.market.cpi.annual_rate_by_year
    # the twelve months after the end of January 2022: eleven of 2022 and January of 2023
    january = t.filter(pl.col("date") == pl.date(2022, 1, 31))["expected_inflation"][0]
    expected = np.exp((11 * np.log1p(rates[2022]) + np.log1p(rates[2023])) / 12) - 1
    assert abs(january - expected) < 1e-5
    # prices rose faster in 2022 than in 2025, and so did the one-year rate
    early = t.filter(pl.col("date") == pl.date(2022, 6, 30))["rate"][0]
    late = t.filter(pl.col("date") == pl.date(2025, 6, 30))["rate"][0]
    assert early > late + 0.1


def test_foreign_curves_do_not_move_with_domestic_prices(clean_baseline):
    r = _feed(clean_baseline, "interest_rates")
    usd = r.filter((pl.col("curve_id") == "USD_TSY") & (pl.col("tenor_months") == 12))["rate"]
    assert usd.min() > 0.0 and usd.max() < 0.1
    assert (
        r.filter((pl.col("curve_id") == "TRY_GOV") & (pl.col("tenor_months") == 12))["rate"].max()
        > 0.4
    )


@pytest.mark.slow
def test_a_higher_inflation_path_gives_higher_rates():
    base = simulate_named("baseline", NO_FAULTS)
    doubled = simulate_named(
        "baseline", {**NO_FAULTS, "market": {"cpi": {"annual_rate_by_year": {2023: 1.3}}}}
    )

    def level(sim) -> float:
        r = _feed(sim, "interest_rates")
        return float(
            r.filter(
                (pl.col("curve_id") == "TRY_GOV")
                & (pl.col("tenor_months") == 12)
                & (pl.col("date") == pl.date(2022, 12, 31))
            )["rate"][0]
        )

    assert level(doubled) > level(base) + 0.2
