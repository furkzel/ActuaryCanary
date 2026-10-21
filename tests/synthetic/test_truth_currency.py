"""Truth files: every money column has a currency, and premium and claims of a row share it."""

import polars as pl
import pytest

from actuarycanary.synthetic.truth import MONEY_COLUMNS, REPORTING, ROW, money_columns_table
from tests.synthetic.conftest import simulate_with

NOT_MONEY = {
    "ultimates": {
        "segment line entity accident_year currency claims_simulated claims_non_nil "
        "claims_reported_at_cutoff fx_cutoff_rate ultimate_loss_ratio"
    },
    "ibnr_by_valuation": {"valuation_date segment line accident_year currency"},
    "frequency_severity": {
        "line accident_year exposure_years claims_regular claims_catastrophe claims_shock "
        "claims_regular_non_nil expected_frequency observed_frequency"
    },
    "development_pattern": {
        "line accident_year lag_years valuation_date observed_at_cutoff paid_share "
        "incurred_share reported_count_share"
    },
    "inflation": None,  # index numbers and rates only; checked below
}

FOREIGN_HEAVY = {
    "lines": {
        "MOTOR_OD": {
            "portfolio": {
                "foreign_currency_share": 0.5,
                "foreign_currencies": {"USD": 0.5, "EUR": 0.5},
            }
        }
    },
    # a quiet exchange rate: premium in a foreign currency follows the rate's random walk, which
    # is a property of the world and would blur a comparison of the two sides
    "market": {
        "fx": [
            {
                "series_id": "USD/TRY",
                "start": 2.95,
                "drift": "inflation_differential",
                "foreign_inflation": 0.03,
                "monthly_vol": 0.002,
            },
            {
                "series_id": "EUR/TRY",
                "start": 3.25,
                "drift": "inflation_differential",
                "foreign_inflation": 0.02,
                "monthly_vol": 0.002,
            },
        ]
    },
    "sizes": {"tiny": {"portfolio_scale": 0.03}},
}
WRITTEN = ["WRITTEN", "ENDORSEMENT", "CANCELLATION", "REFUND"]


@pytest.fixture(scope="module")
def foreign():
    return simulate_with(FOREIGN_HEAVY)


def test_cv01_every_money_column_of_every_truth_file_has_a_currency(baseline):
    for name, table in baseline.truth.items():
        listed = set(MONEY_COLUMNS[name])
        if name == "inflation":
            assert not listed and all(
                c in ("month_end", "observed_in_files") or c.startswith(("cpi", "claims_index"))
                for c in table.columns
            )
            continue
        unmoney = set(NOT_MONEY[name].pop().split())
        assert set(table.columns) == listed | unmoney, name
        assert not listed & unmoney
        assert {basis for basis, _ in MONEY_COLUMNS[name].values()} <= {ROW, REPORTING}
    written = money_columns_table()
    assert written.height == sum(len(c) for c in MONEY_COLUMNS.values())
    reporting = written.filter(pl.col("currency") == REPORTING)
    assert all(len(how) > 0 for how in reporting["conversion"])
    assert all("try" in column for column in reporting["column"])  # the name says it too


def test_cv01_reporting_columns_are_row_columns_at_the_cutoff_rate(baseline):
    u = baseline.truth["ultimates"]
    assert (u["fx_cutoff_rate"] > 0).all()
    for original, reporting in (
        ("ultimate_gross", "ultimate_try_at_cutoff_rate"),
        ("earned_premium", "earned_premium_try_at_cutoff_rate"),
    ):
        assert (u[original] * u["fx_cutoff_rate"] - u[reporting]).abs().max() < 1e-6
    assert (u.filter(pl.col("currency") == "TRY")["fx_cutoff_rate"] == 1.0).all()
    assert u.filter(pl.col("currency") != "TRY").height > 0


def test_cv01_premium_and_claims_of_a_row_are_in_the_currency_of_the_row(foreign):
    """Both sides are compared with the data feeds, which carry their own currency code."""
    u = foreign.truth["ultimates"]
    assert set(u["currency"]) == {"TRY", "USD", "EUR"}
    policy = foreign.clean["policies"].select("policy_id", "line")
    premiums = foreign.clean["premiums"].filter(pl.col("type").is_in(WRITTEN))
    written = (
        premiums.join(policy, on="policy_id")
        .group_by("line", "currency")
        .agg(pl.col("amount").sum().alias("written"))
    )
    earned = u.group_by("line", "currency").agg(pl.col("earned_premium").sum())
    joined = earned.join(written, on=["line", "currency"])
    assert joined.height == earned.height
    share = joined["earned_premium"] / joined["written"]
    # earning only lags writing; a TRY amount labelled USD would be 20 to 30 times too large
    assert share.min() > 0.4 and share.max() <= 1.0 + 1e-9

    last = (
        foreign.clean["claim_valuations"]
        .sort("valuation_date")
        .group_by("claim_id")
        .agg(pl.col("paid_to_date").last(), pl.col("currency").last())
    )
    paid_feed = last.group_by("currency").agg(pl.col("paid_to_date").sum()).sort("currency")
    paid_truth = u.group_by("currency").agg(pl.col("paid_at_cutoff").sum()).sort("currency")
    assert paid_feed["currency"].to_list() == paid_truth["currency"].to_list()
    assert paid_truth["paid_at_cutoff"].to_list() == pytest.approx(
        paid_feed["paid_to_date"].to_list(), rel=1e-6
    )


def test_cv01_loss_ratios_are_of_the_same_order_in_every_currency(foreign):
    """A foreign claim was once divided by the starting rate twice, which put the ratios of USD
    and EUR rows at 0.15 to 0.35 times the TRY ratio. Currencies still differ somewhat: TRY
    claims inflate between writing and payment, foreign ones barely do."""
    u = foreign.truth["ultimates"].filter(pl.col("line") == "MOTOR_OD")
    by_currency = u.group_by("currency").agg(
        (pl.col("ultimate_gross").sum() / pl.col("earned_premium").sum()).alias("ratio"),
        pl.col("claims_non_nil").sum().alias("claims"),
    )
    ratio = {r["currency"]: r["ratio"] for r in by_currency.iter_rows(named=True)}
    assert min(r["claims"] for r in by_currency.iter_rows(named=True)) >= 100
    for currency in ("USD", "EUR"):
        assert 0.5 < ratio[currency] / ratio["TRY"] < 2.0, ratio
    pooled = u["ultimate_try_at_cutoff_rate"].sum() / u["earned_premium_try_at_cutoff_rate"].sum()
    assert 0.5 < pooled / ratio["TRY"] < 2.0
