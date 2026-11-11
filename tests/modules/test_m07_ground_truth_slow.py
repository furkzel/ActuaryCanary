"""M07 against the truth of the generator on baseline medium (slow; needs
data/synthetic/baseline/medium, written with `just synth baseline medium`)."""

from pathlib import Path

import polars as pl
import pytest

from actuarycanary.modules.recoveries import recovery_tables
from actuarycanary.pipeline import RunSettings, run

MEDIUM = Path("data/synthetic/baseline/medium")
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not MEDIUM.is_dir(), reason="data/synthetic/baseline/medium is missing"),
]


def test_recoveries_of_the_run_equal_the_truth_booked_by_the_cut_off(tmp_path) -> None:
    result = run(MEDIUM, tmp_path / "out", RunSettings(), cache_dir=tmp_path / "cache")
    assert result.analysis.inputs is not None
    tables = recovery_tables(result.analysis.inputs)
    truth = pl.read_csv(MEDIUM / "truth" / "recoveries_truth.csv", try_parse_dates=True)
    booked = truth.filter(pl.col("booked_by_cutoff"))
    assert tables.source == "transactions"
    by = ["type"]
    got = tables.flows.group_by(by).agg(pl.col("amount").sum().round(0)).sort(by)
    want = (
        booked.group_by(by).agg(pl.col("recovery_amount").sum().round(0).alias("amount")).sort(by)
    )
    assert got.equals(want)
    assert tables.reconciliation.height == 0  # the transactions add up to the to-date fields
    m07 = result.analysis.get("M07")
    assert {m.measure for m in m07.available} == {"RC01", "RC02", "RC03", "RC04"}
