"""The life and pension book: the model is in the truth, the feeds follow CV11."""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.life import BIG, gompertz_makeham, jan1_days, whole_years
from tests.synthetic.conftest import NO_FAULTS, simulate_named


def _feed(sim, name):
    return sim.phase2.frames[name][name]


def test_the_life_feeds_are_only_written_when_the_book_is_enabled(clean_baseline, life):
    assert not {"life_in_force", "life_events", "fund_flows"} & set(clean_baseline.frames)
    assert {"life_in_force", "life_events", "fund_flows"} <= set(life.frames)


def test_every_contract_is_in_the_data_from_the_first_valuation_until_its_exit(life):
    g = _feed(life, "life_in_force")
    truth = life.phase2.truth["life_contracts"].filter(pl.col("in_data"))
    rows = g.group_by("contract_id").agg(
        pl.col("valuation_date").min().alias("first"),
        pl.col("valuation_date").max().alias("last"),
        pl.len().alias("n"),
    )
    assert set(rows["contract_id"]) == set(truth["contract_id"])
    cut_off = life.scenario.meta.valuation.last
    joined = rows.join(truth, on="contract_id")
    # no row after the cut-off; a contract that exited before the cut-off stops at the first
    # valuation on or after its exit (a death at the first valuation after it is reported)
    assert (joined["last"] <= cut_off).all()
    stopped = joined.filter(pl.col("last") < cut_off)
    assert (stopped["exit_date"] <= stopped["last"]).all()
    # the number of rows is the number of year ends between the first and last row
    years = joined["last"].dt.year() - joined["first"].dt.year() + 1
    assert (joined["n"] == years).all()


def test_age_moves_on_policy_anniversaries_as_cv11_reads_it(life):
    g = _feed(life, "life_in_force").filter(pl.col("product") == "TERM_LIFE")
    truth = life.phase2.truth["life_contracts"].select("contract_id", "entry_age")
    joined = g.join(truth, on="contract_id")
    entry = joined["entry_date"].to_numpy().astype("datetime64[D]").astype(np.int64)
    at = joined["valuation_date"].to_numpy().astype("datetime64[D]").astype(np.int64)
    expected = joined["entry_age"].to_numpy() + whole_years(entry, at)
    assert (joined["age_band"].cast(pl.Int64).to_numpy() == expected).all()
    banded = _feed(life, "life_in_force").filter(pl.col("product") == "GROUP_TERM")
    assert banded["age_band"].str.contains(r"^\d+-\d+$").all()
    low = banded["age_band"].str.split("-").list.get(0).cast(pl.Int64)
    high = banded["age_band"].str.split("-").list.get(1).cast(pl.Int64)
    assert ((high - low) == 4).all() and (low % 5 == 0).all()


def test_exposure_in_the_truth_is_the_sum_of_the_individual_exposures(life_big):
    """Central exposure in years (days / 365.25) of every contract over the observed window,
    added up from the timelines of the contract table, equals the exposure of the cells."""
    cells = life_big.phase2.truth["life_expected_decrements"]
    contracts = life_big.phase2.truth["life_contracts"].filter(pl.col("in_data"))
    cut_off = to_day(life_big.scenario.meta.valuation.last) + 1
    start = to_day(date(life_big.scenario.sizes["tiny"].years[0], 1, 1))

    def days(column: str, default: int) -> np.ndarray:
        values = contracts[column].to_numpy().astype("datetime64[D]").astype(np.int64)
        return np.where(contracts[column].is_null().to_numpy(), default, values)

    def span(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        low, high = np.maximum(lo, start), np.minimum(hi, cut_off)
        return np.maximum(high - low, 0)

    entry = days("entry_date", cut_off)
    first_exit = days("first_exit_date", cut_off)
    final_exit = days("exit_date", cut_off)
    restart = days("reinstatement_date", cut_off)
    reinstated = contracts["reinstated"].to_numpy()
    total = span(entry, first_exit).sum() + span(restart, final_exit)[reinstated].sum()
    assert contracts["reinstated"].sum() > 0
    assert abs(cells["exposure_years"].sum() - total / 365.25) < 1e-6


def test_actual_decrements_in_the_truth_are_the_events_of_the_feed(life_big):
    cells = life_big.phase2.truth["life_expected_decrements"]
    events = _feed(life_big, "life_events")
    deaths = events.filter(pl.col("event_type") == "DEATH").height
    assert deaths == cells["deaths_reported"].sum()
    lapses = events.filter(pl.col("event_type") == "LAPSE").height
    surrenders = events.filter(pl.col("event_type") == "SURRENDER").height
    assert cells["lapses"].sum() == lapses + surrenders
    assert (cells["deaths"] >= cells["deaths_reported"]).all()


def test_the_reference_table_is_the_model_before_the_multipliers(life):
    book = life.scenario.phase2.life_book
    table = life.phase2.files["reference_tables/reference_mortality.csv"]
    mu = gompertz_makeham(book, table["age"].to_numpy())
    assert np.allclose(table["rate"].to_numpy(), 1.0 - np.exp(-mu), atol=1e-8)
    assert set(table["rate_kind"]) == {"q"}
    truth = life.phase2.truth["life_mortality_truth"]
    ratio = truth["true_force"] / truth["reference_force"]
    assert np.allclose(ratio.to_numpy(), truth["multiplier"].to_numpy(), rtol=1e-6)
    by_product = (
        truth.filter(pl.col("sex") == "FEMALE")
        .group_by("product")
        .agg(pl.col("multiplier").first())
    )
    expected = {p.key: p.mortality_multiplier * book.mortality.female_factor for p in book.products}
    assert {
        k: round(v, 9) for k, v in zip(by_product["product"], by_product["multiplier"], strict=True)
    } == {k: round(v, 9) for k, v in expected.items()}
    lapse = life.phase2.truth["life_lapse_truth"]
    assert np.allclose(
        (lapse["true_rate"] / lapse["reference_rate"]).to_numpy(),
        lapse["lapse_multiplier"].to_numpy(),
        rtol=1e-9,
    )
    reference = life.phase2.files["reference_tables/reference_lapse.csv"]
    assert set(reference["product"]) == {p.key for p in book.products}


def test_statuses_events_and_reinstatements_agree(life_big):
    g = _feed(life_big, "life_in_force").sort(["contract_id", "valuation_date"])
    events = _feed(life_big, "life_events")
    terminal = events.filter(
        pl.col("event_type").is_in(["DEATH", "SURRENDER", "LAPSE", "MATURITY", "TRANSFER_OUT"])
    )
    status = {
        "DEATH": "DEATH_CLAIM",
        "SURRENDER": "SURRENDERED",
        "LAPSE": "LAPSED",
        "MATURITY": "MATURED",
        "TRANSFER_OUT": "TRANSFERRED_OUT",
    }
    exits = g.filter(pl.col("status") != "IN_FORCE").select(
        "contract_id", "status", "valuation_date"
    )
    last = exits.group_by("contract_id").agg(pl.col("status").last())
    joined = terminal.join(last, on="contract_id", how="inner")
    assert joined.height > 20
    expected = joined["event_type"].replace_strict(status)
    # a contract that was reinstated can exit again; compare contracts with one terminal event
    once = joined.group_by("contract_id").agg(pl.len().alias("n"))
    single = joined.join(once.filter(pl.col("n") == 1), on="contract_id")
    assert (single["status"] == single["event_type"].replace_strict(status)).all()
    del expected
    reinstated = events.filter(pl.col("event_type") == "REINSTATEMENT")
    assert reinstated.height > 0
    after = g.join(
        reinstated.select("contract_id", pl.col("event_date").alias("back")), on="contract_id"
    )
    later = after.filter(pl.col("valuation_date") > pl.col("back"))
    assert later.height > 0 and set(later["status"]) <= {
        "IN_FORCE",
        "LAPSED",
        "SURRENDERED",
        "DEATH_CLAIM",
        "MATURED",
        "TRANSFERRED_OUT",
    }


def test_fund_flows_have_every_type_and_switches_net_to_zero(life):
    f = _feed(life, "fund_flows")
    assert {
        "CONTRIBUTION",
        "STATE_CONTRIBUTION",
        "EMPLOYER_CONTRIBUTION",
        "FEE",
        "BENEFIT_PAYMENT",
        "FUND_SWITCH",
    } <= set(f["flow_type"])
    switches = f.filter(pl.col("flow_type") == "FUND_SWITCH")
    assert switches["fund_code"].null_count() == 0
    net = switches.group_by(["contract_id", "flow_date"]).agg(pl.col("amount").sum())
    assert net["amount"].abs().max() < 0.011
    others = f.filter(pl.col("flow_type") != "FUND_SWITCH")
    assert (others["amount"] > 0).all()
    state = f.filter(pl.col("flow_type") == "STATE_CONTRIBUTION")["amount"].sum()
    member = f.filter(pl.col("flow_type") == "CONTRIBUTION")["amount"].sum()
    assert 0.1 < state / member < 0.26  # a quarter of the pension contributions only


def test_helpers_count_whole_years_and_find_january_first():
    from datetime import date

    entry = np.array([to_day(date(2020, 2, 29)), to_day(date(2021, 6, 15))])
    day = np.array([to_day(date(2021, 2, 28)), to_day(date(2022, 6, 14))])
    assert whole_years(entry, day).tolist() == [1, 0]
    assert jan1_days(np.array([1970, 2000])).tolist() == [0, to_day(date(2000, 1, 1))]
    assert to_day(date(2200, 1, 1)) < BIG


@pytest.mark.slow
def test_a_larger_book_gives_actual_decrements_near_the_true_expected_ones():
    """Poisson sampling: the actual deaths and lapses of each product are within four standard
    errors of what the true model expects over the exposure that was observed."""
    sim = simulate_named("life_book", {**NO_FAULTS, "sizes": {"tiny": {"portfolio_scale": 0.05}}})
    cells = sim.phase2.truth["life_expected_decrements"]
    by_product = cells.group_by("product").agg(
        pl.col("expected_deaths").sum(),
        pl.col("deaths").sum(),
        pl.col("expected_lapses").sum(),
        pl.col("lapses").sum(),
    )
    for row in by_product.iter_rows(named=True):
        assert (
            abs(row["deaths"] - row["expected_deaths"]) < 4 * max(row["expected_deaths"], 1) ** 0.5
        ), row
        assert (
            abs(row["lapses"] - row["expected_lapses"]) < 4 * max(row["expected_lapses"], 1) ** 0.5
        ), row
