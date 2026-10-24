"""Lineage of the method outputs RS01 to RS03 (decision 0071): every row names source rows."""

import polars as pl
import pytest

from actuarycanary.pipeline import RunResult

pytestmark = pytest.mark.integration


def test_method_outputs_name_the_valuation_rows_behind_them(default_run: RunResult) -> None:
    lineage = pl.read_csv(default_run.folder / "lineage.csv", infer_schema_length=0)
    for measure in ("RS01", "RS02"):
        rows = lineage.filter(pl.col("measure") == measure)
        assert rows.height > 0 and set(rows["concept"]) == {"claim_valuations"}
    rs02 = default_run.analysis.get("M04").measures[1]
    assert rs02.measure == "RS02" and rs02.frame is not None
    # a row of one origin lists fewer rows than the whole line, which RS01 rows list
    first = lineage.filter((pl.col("measure") == "RS02") & (pl.col("row") == "0"))
    line = lineage.filter((pl.col("measure") == "RS01") & (pl.col("row") == "0"))
    assert 0 < int(first["count"][0]) < int(line["count"][0])


@pytest.mark.slow  # the first read of the 5 MB page takes over a second on a scanned disk
def test_the_appendix_says_which_lineage_format_the_run_wrote(default_run: RunResult) -> None:
    page = default_run.report.read_text(encoding="utf-8")
    assert "Lineage format 2" in page and "lineage_atoms.csv" in page
    assert "built-in method" not in page  # a summary key must not shadow a dict method
    summary = default_run.report_data["lineage"]
    assert f"{summary['traced_values']} values cite {summary['rows_cited']} source rows" in page
