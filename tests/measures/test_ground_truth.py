"""Measures on the synthetic baseline (medium) against its ground truth, where the truth has it.

Claim amounts, counts, earned premium and exposure are compared cell by cell with
`truth/ultimates.csv` and `truth/frequency_severity.csv`. Cells of claims with an injected payment
fault (extreme payment, decreasing paid_to_date) are compared within a quarter of the cell.
"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.convert.market import MarketData
from actuarycanary.convert.rates import development_rates
from actuarycanary.io.excel import RawTable, read_workbook
from actuarycanary.measures.model import CurrencyView, MeasureInputs, with_refs
from actuarycanary.spec.loader import load_specs
from tests.measures.helpers import measure

ROOT = Path(__file__).parents[2]
MEDIUM = ROOT / "data" / "synthetic" / "baseline" / "medium"
CACHE = ROOT / ".cache"

pytestmark = [pytest.mark.slow, pytest.mark.integration]

RELATIVE = 1e-9


@pytest.fixture(scope="module")
def inputs() -> MeasureInputs:
    if not MEDIUM.exists():
        pytest.skip("run `just synth baseline medium` first")
    specs = load_specs()
    feeds: dict[str, pl.DataFrame] = {}
    for concept in ("claim_valuations", "claims", "policies", "premiums", "market"):
        table = read_workbook(MEDIUM / f"{concept}.xlsx", CACHE).tables[0]
        raw = RawTable(table.sheet, table.frame.rename({c: c for c in table.frame.columns}))
        feeds[concept] = canonicalise(raw, specs.data[concept]).frame
    cut_off = feeds["claim_valuations"]["valuation_date"].max()
    assert isinstance(cut_off, date)
    market = MarketData.from_frame(feeds["market"])
    currencies = feeds["claim_valuations"]["currency"].drop_nulls().unique().to_list()
    rates = development_rates("TRY", currencies, market, cut_off)
    return MeasureInputs(with_refs(feeds), cut_off, "TRY", rates, market, "CPI_TR")  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def truth() -> pl.DataFrame:
    if not MEDIUM.exists():
        pytest.skip("run `just synth baseline medium` first")
    return pl.read_csv(MEDIUM / "truth" / "ultimates.csv")


def _year(frame: pl.DataFrame, column: str) -> pl.DataFrame:
    return frame.with_columns(pl.col(column).cast(pl.Int64).alias("accident_year"))


def _fault_cells(inputs: MeasureInputs) -> pl.DataFrame:
    """Segment, line, accident year and currency of the claims with an injected payment fault:
    an extreme payment, or a paid_to_date that decreases without a reason."""
    faults = pl.read_csv(MEDIUM / "truth" / "injected_faults.csv", infer_schema=False).filter(
        pl.col("fault_type").is_in(["extreme_payment_outliers"])
        | pl.col("fault_type").str.starts_with("paid_to_date_decreasing")
    )
    claim_ids = faults["key"].str.split("|").list.first().unique()
    claims = inputs.feeds["claims"].filter(pl.col("claim_id").is_in(claim_ids.implode()))
    currency = (
        inputs.feeds["claim_valuations"]
        .filter(pl.col("claim_id").is_in(claim_ids.implode()))
        .group_by("claim_id")
        .agg(pl.col("currency").drop_nulls().first())
    )
    return (
        claims.join(currency, on="claim_id")
        .select(
            "segment",
            "line",
            pl.col("occurrence_date").dt.year().alias("accident_year"),
            "currency",
        )
        .unique()
    )


@pytest.mark.parametrize(
    ("measure_id", "column"),
    [
        ("CL01", "paid_at_cutoff"),
        ("CL02", "case_reserve_at_cutoff"),
        ("CL03", "incurred_at_cutoff"),
    ],
)
def test_claim_amounts_equal_the_truth_in_every_cell_without_an_injected_payment_fault(
    inputs: MeasureInputs, truth: pl.DataFrame, measure_id: str, column: str
) -> None:
    result = measure(
        inputs, measure_id, "segment", "line", "origin_period", currency=CurrencyView.ORIGINAL
    )
    assert result.frame is not None
    key = ["segment", "line", "accident_year", "currency"]
    expected = truth.group_by(key).agg(pl.col(column).sum().alias("truth"))
    both = _year(result.frame, "origin_period").join(expected, on=key, how="full", coalesce=True)
    assert both["value"].null_count() == 0 and both["truth"].null_count() == 0
    touched = _fault_cells(inputs).with_columns(pl.lit(True).alias("touched"))
    both = both.join(touched, on=key, how="left").with_columns(pl.col("touched").fill_null(False))
    clean = both.filter(~pl.col("touched"))
    assert clean.height > 40
    gap = ((clean["value"] - clean["truth"]).abs() / clean["truth"].clip(lower_bound=1.0)).max()
    assert gap < RELATIVE  # type: ignore[operator]
    faulty = both.filter(pl.col("touched"))
    assert faulty.height >= 8
    # a fault moves a cell by a payment or a decrease: far less than a quarter of the cell
    assert ((faulty["value"] - faulty["truth"]).abs() / faulty["truth"]).max() < 0.25  # type: ignore[operator]


def test_case_reserve_in_the_reporting_currency_is_the_truth_at_the_constant_cutoff_rate(
    inputs: MeasureInputs, truth: pl.DataFrame
) -> None:
    result = measure(inputs, "CL02", "segment", "line", "origin_period")
    assert result.frame is not None
    key = ["segment", "line", "accident_year"]
    expected = (
        truth.with_columns((pl.col("case_reserve_at_cutoff") * pl.col("fx_cutoff_rate")).alias("t"))
        .group_by(key)
        .agg(pl.col("t").sum())
    )
    both = _year(result.frame, "origin_period").join(expected, on=key)
    assert both.height == 40
    assert ((both["value"] - both["t"]).abs() / both["t"].clip(lower_bound=1.0)).max() < 1e-9  # type: ignore[operator]


def test_reported_claim_counts_equal_the_truth(inputs: MeasureInputs, truth: pl.DataFrame) -> None:
    result = measure(inputs, "CL04", "segment", "line", "origin_period")
    assert result.frame is not None
    counts = _year(result.frame.filter(pl.col("count_type") == "reported"), "origin_period")
    key = ["segment", "line", "accident_year"]
    expected = truth.group_by(key).agg(pl.col("claims_reported_at_cutoff").sum().alias("truth"))
    both = counts.join(expected, on=key)
    assert both.height == 40
    assert (both["value"] == both["truth"]).all()


def test_earned_premium_equals_the_truth_by_entity_year_and_currency(
    inputs: MeasureInputs, truth: pl.DataFrame
) -> None:
    result = measure(
        inputs,
        "PR02",
        "segment",
        "line",
        "entity",
        "calendar_period",
        currency=CurrencyView.ORIGINAL,
    )
    assert result.frame is not None
    key = ["segment", "line", "entity", "accident_year", "currency"]
    expected = truth.group_by(key).agg(pl.col("earned_premium").sum().alias("truth"))
    both = _year(result.frame, "calendar_period").join(expected, on=key)
    assert both.height == expected.height
    assert ((both["value"] - both["truth"]).abs() / both["truth"]).max() < 1e-9  # type: ignore[operator]


def test_frequency_has_the_truth_exposure_and_counts_reported_claims_that_are_not_nil(
    inputs: MeasureInputs,
) -> None:
    result = measure(inputs, "CL05", "line", "origin_period")
    assert result.frame is not None
    exposure_truth = pl.read_csv(MEDIUM / "truth" / "frequency_severity.csv")
    both = _year(result.frame, "origin_period").join(exposure_truth, on=["line", "accident_year"])
    assert both.height == exposure_truth.height
    gap = (both["denominator"] - both["exposure_years"]).abs() / both["exposure_years"]
    assert gap.max() < 1e-9  # type: ignore[operator]
    counts = measure(inputs, "CL04", "line", "origin_period")
    assert counts.frame is not None
    by_type = _year(counts.frame, "origin_period").pivot(
        on="count_type", index=["line", "accident_year"], values="value"
    )
    counted = both.join(by_type, on=["line", "accident_year"])
    # frequency counts the claims reported by the cut-off that are not nil-closed
    assert (counted["numerator"] == counted["reported"] - counted["nil_closed"]).all()


def test_premium_net_of_ceded_is_gross_minus_ceded_on_the_medium_file(
    inputs: MeasureInputs,
) -> None:
    gross = measure(inputs, "PR01", "calendar_period", currency=CurrencyView.REPORTING)
    ceded = measure(
        inputs,
        "PR01",
        "calendar_period",
        reinsurance=ReinsuranceBasis.CEDED,
        currency=CurrencyView.REPORTING,
    )
    net = measure(
        inputs,
        "PR01",
        "calendar_period",
        reinsurance=ReinsuranceBasis.NET,
        currency=CurrencyView.REPORTING,
    )
    assert gross.frame is not None and ceded.frame is not None and net.frame is not None
    difference = gross.frame["value"] - ceded.frame["value"] - net.frame["value"]
    assert difference.abs().max() < 1e-6  # type: ignore[operator]
