"""M10 against the generator's truth (record 0244): on a tiny scenario without injected faults the
material gaps are the written ones, the unmapped share is the suspense account's, and the
suggested causes are compared with the written ones."""

from datetime import date

import polars as pl
import pytest

from actuarycanary.modules.ledger_reconciliation import LedgerTables, ledger_tables
from actuarycanary.synthetic.build import simulate
from actuarycanary.synthetic.scenario import load_with
from tests.ledger.scenario_inputs import inputs_of
from tests.synthetic.conftest import NO_FAULTS

WRITTEN_AS = {
    "premium_timing": "CUT_OFF_TIMING",
    "ibnr_in_outstanding": "IBNR_IN_OUTSTANDING",
    "translation": "CURRENCY",
    "unmapped_account": "UNMAPPED_ACCOUNT",
}
RATIO = 0.005


@pytest.fixture(scope="module")
def world():
    sim = simulate(load_with("reinsurance_heavy", NO_FAULTS), "tiny")
    return sim, ledger_tables(inputs_of(sim))


def keys(frame: pl.DataFrame) -> set[tuple[str, str, date]]:
    return {(r["entity"], r["account_class"], r["period"]) for r in frame.iter_rows(named=True)}


def test_the_material_gaps_are_the_written_ones(world) -> None:
    sim, tables = world
    truth = sim.phase2.truth["ledger_gaps"]
    written = truth.filter(
        (pl.col("gap").abs() > RATIO * pl.col("ledger_amount").abs())
        & (pl.col("gap").abs() > 0.005)
    )
    found = tables.material.filter(pl.col("account_class") != "RI")
    assert keys(found) == keys(written)
    assert found.height == written.height == 20  # 4 months of premium timing, 16 of IBNR
    for row in found.iter_rows(named=True):  # and the gap is the written one, within the rate
        theirs = written.filter(
            (pl.col("entity") == row["entity"])
            & (pl.col("account_class") == row["account_class"])
            & (pl.col("period") == row["period"])
        ).row(0, named=True)
        assert row["gap"] == pytest.approx(theirs["gap"], rel=1e-3)
        assert row["ledger_amount"] == pytest.approx(theirs["ledger_amount"], abs=1.0)


def test_a_written_gap_under_the_materiality_is_not_flagged(world) -> None:
    sim, tables = world
    translation = sim.phase2.truth["ledger_differences"].filter(pl.col("kind") == "translation")
    assert translation.height == 1
    row = tables.reconciliation.filter(
        (pl.col("entity") == translation["entity"][0])
        & (pl.col("account_class") == "PREMIUM")
        & (pl.col("period") == translation["period"][0])
    ).row(0, named=True)
    assert abs(row["gap"]) > 1000 and abs(row["share"]) < RATIO and not row["material"]


def test_the_gaps_in_ri_are_the_rate_convention_of_the_generator_not_written_ones(world) -> None:
    """The generator converts premium flows at the monthly average rate, the platform at the rate
    of the booking date (CV01): ceded premium, a part of RI, differs by that. The truth has no RI
    gap; the module finds a few small ones, in foreign-currency months, and says currency."""
    sim, tables = world
    truth = sim.phase2.truth["ledger_gaps"].filter(pl.col("account_class") == "RI")
    assert truth["gap"].abs().max() == 0
    ri = tables.material.filter(pl.col("account_class") == "RI")
    assert 0 < ri.height <= 10
    assert (ri["suggested_causes"] == "CURRENCY").all()
    assert ri["gap"].abs().max() < 5000


def test_the_unmapped_share_is_the_suspense_account(world) -> None:
    sim, tables = world
    ledger = pl.concat(sim.frames["ledger"].values())
    assert tables.unmapped.height == 1
    row = tables.unmapped.row(0, named=True)
    assert (row["entity"], row["account"]) == ("ENT_A", "297")
    suspense = ledger.filter(pl.col("account") == "297")
    assert row["latest_balance"] == suspense.sort("period")["closing_balance"][-1]
    total = ledger.group_by("entity", "period").agg(
        pl.col("closing_balance").abs().sum().alias("all")
    )
    mine = (
        suspense.group_by("entity", "period")
        .agg(pl.col("closing_balance").abs().sum().alias("part"))
        .join(total, on=["entity", "period"])
        .with_columns((pl.col("part") / pl.col("all")).alias("expected"))
    )
    got = tables.share.join(mine, on=["entity", "period"], how="inner")
    assert got.height == mine.height > 10
    assert (got["value"] - got["expected"]).abs().max() < 1e-12
    other = tables.share.filter(pl.col("entity") != "ENT_A")
    assert (other["value"] == 0).all()


def test_the_suggested_causes_against_the_written_ones(world) -> None:
    """Information: how many of the written causes the module suggests. Each written cause of a
    material gap is among the suggestions."""
    sim, tables = world
    written = sim.phase2.truth["ledger_gaps"].filter(pl.col("cause").is_not_null())
    material = tables.material.join(
        written.select("entity", "account_class", "period", "cause"),
        on=["entity", "account_class", "period"],
        how="inner",
    )
    assert material.height == 20
    hits = sum(
        WRITTEN_AS[r["cause"]] in r["suggested_causes"].split("; ")
        for r in material.iter_rows(named=True)
    )
    assert hits == material.height
    assert tables.material["suggested_causes"].str.contains("no cause suggested").sum() == 0


def test_every_row_says_that_the_profile_is_only_proposed(world) -> None:
    _, tables = world
    assert isinstance(tables, LedgerTables)
    assert set(tables.reconciliation["ledger_mapping"]) == {"proposed, not confirmed"}
    assert tables.mapping == "proposed, not confirmed"
