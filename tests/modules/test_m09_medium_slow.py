"""M09 on baseline medium (slow; needs data/synthetic/baseline/medium, written with
`just synth baseline medium`): the table adds up to the expenses file and nothing is spread."""

from pathlib import Path

import polars as pl
import pytest

from actuarycanary.modules.expenses import NOMINAL, expense_table
from actuarycanary.pipeline import RunSettings, run

MEDIUM = Path("data/synthetic/baseline/medium")
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not MEDIUM.is_dir(), reason="data/synthetic/baseline/medium is missing"),
]


def test_the_expense_table_adds_up_to_the_file_at_every_level(tmp_path) -> None:
    result = run(MEDIUM, tmp_path / "out", RunSettings(), cache_dir=tmp_path / "cache")
    assert result.analysis.inputs is not None
    table = expense_table(result.analysis.inputs)
    source = pl.read_parquet(MEDIUM / "canonical" / "expenses.parquet")
    one_currency = source["currency"].n_unique() == 1
    if one_currency:
        assert table.frame[NOMINAL].sum() == pytest.approx(source["amount"].sum(), rel=1e-9)
    booked_without_line = source.filter(pl.col("line").is_null()).height
    assert table.unallocated["rows"].sum() == booked_without_line
    m09 = result.analysis.get("M09")
    assert {m.measure for m in m09.available} == {"EX01", "EX02", "EX03", "EX04", "EX05"}
