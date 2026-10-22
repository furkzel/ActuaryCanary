"""Synthetic medium data for the ground-truth tests of the methods (slow, git-ignored data).

Feeds are read from the spreadsheets through the parquet cache and canonicalised, as a run
would. `repair_amount_faults` undoes the known effect of the injected amount faults, so that
a method is compared with the truth and not with the faults.
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.convert.market import MarketData
from actuarycanary.convert.rates import DevelopmentRates, development_rates
from actuarycanary.io.excel import RawTable, read_workbook
from actuarycanary.spec.loader import load_specs

ROOT = Path(__file__).parents[2]
DATA = ROOT / "data" / "synthetic"
CACHE = ROOT / ".cache"
AMOUNT_FAULTS = ("extreme_payment_outliers", "paid_to_date_decreasing_without_recovery")


def medium(scenario: str) -> Path:
    return DATA / scenario / "medium"


@dataclass(frozen=True)
class Medium:
    valuations: pl.DataFrame
    claims: pl.DataFrame
    market: MarketData
    rates: DevelopmentRates  # constant development rates at the cut-off (CV01)
    faults: pl.DataFrame  # injected_faults.csv with claim_id and valuation_date split out
    truth: Path


def load_medium(scenario: str) -> Medium:
    return load_folder(medium(scenario))


def load_folder(folder: Path) -> Medium:
    """Canonical feeds of a synthetic folder; `faults` is empty when it has no truth."""
    specs = load_specs()

    def feed(name: str, concept: str) -> pl.DataFrame:
        workbook = read_workbook(folder / f"{name}.xlsx", CACHE)
        table = RawTable(
            name, pl.concat([t.frame for t in workbook.tables], how="diagonal_relaxed")
        )
        return canonicalise(table, specs.data[concept]).frame

    valuations = feed("claim_valuations", "claim_valuations")
    market = MarketData.from_frame(feed("market", "market"))
    cut_off = valuations["valuation_date"].max()
    currencies = valuations["currency"].drop_nulls().unique().to_list()
    truth = folder / "truth" / "injected_faults.csv"
    columns = {"fault_type": pl.String, "file": pl.String, "key": pl.String, "detail": pl.String}
    faults = (
        pl.read_csv(truth, schema_overrides={"key": pl.String})
        if truth.exists()
        else pl.DataFrame(schema=columns)
    ).with_columns(
        pl.col("key").str.split("|").list.get(0).alias("claim_id"),
        pl.col("key").str.split("|").list.get(1, null_on_oob=True).str.to_date().alias("date"),
    )
    return Medium(
        valuations,
        feed("claims", "claims"),
        market,
        development_rates("TRY", currencies, market, cut_off),  # type: ignore[arg-type]
        faults,
        folder / "truth",
    )


def repair_amount_faults(valuations: pl.DataFrame, faults: pl.DataFrame) -> pl.DataFrame:
    """Subtract each injected spike from its row on; drop each row whose paid was lowered."""
    spikes = faults.filter(pl.col("fault_type") == "extreme_payment_outliers").select(
        "claim_id",
        pl.col("date").alias("from_date"),
        pl.col("detail").str.extract(r"payment of ([0-9.]+)").cast(pl.Float64).alias("spike"),
    )
    lowered = faults.filter(
        pl.col("fault_type") == "paid_to_date_decreasing_without_recovery"
    ).select("claim_id", pl.col("date").alias("valuation_date"))
    later = pl.col("valuation_date") >= pl.col("from_date")
    return (
        valuations.join(spikes, on="claim_id", how="left")
        .with_columns(
            pl.when(later)
            .then(pl.col("paid_to_date") - pl.col("spike"))
            .otherwise(pl.col("paid_to_date"))
            .alias("paid_to_date")
        )
        .drop("from_date", "spike")
        .join(lowered, on=["claim_id", "valuation_date"], how="anti")
    )
