"""A feed larger than a worksheet is written as several workbooks (record 0081)."""

import json
from pathlib import Path

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st
from polars.testing import assert_frame_equal

from actuarycanary.synthetic import writer
from actuarycanary.synthetic.build import locate
from actuarycanary.synthetic.messy import SheetPlan
from actuarycanary.synthetic.writer import split_workbooks
from tests.synthetic.conftest import FIXTURES


def plan(rows: int, titles: int = 0) -> SheetPlan:
    return SheetPlan("data", [["note"]] * titles, ["a"], [list(range(rows))])


def test_a_feed_that_fits_stays_one_workbook_named_after_the_feed(monkeypatch):
    monkeypatch.setattr(writer, "EXCEL_MAX_ROWS", 10)
    sheets = [plan(9)]  # header row and 9 data rows
    assert split_workbooks("premiums", sheets) == [("premiums.xlsx", sheets)]


def test_a_feed_that_does_not_fit_is_cut_into_numbered_parts(monkeypatch):
    monkeypatch.setattr(writer, "EXCEL_MAX_ROWS", 10)
    parts = split_workbooks("premiums", [plan(25, titles=1)])  # 8 data rows fit in a worksheet
    assert [name for name, _ in parts] == [
        "premiums_part1.xlsx",
        "premiums_part2.xlsx",
        "premiums_part3.xlsx",
        "premiums_part4.xlsx",
    ]
    assert [p[1][0].n_rows for p in parts] == [7, 7, 7, 4]
    first = parts[0][1][0]
    assert first.title_rows == [["note"]] and first.headers == ["a"] and first.header_row == 2


@given(rows=st.integers(1, 400), limit=st.integers(3, 60), titles=st.integers(0, 2))
def test_the_parts_hold_every_row_once_in_order_and_each_fits(rows, limit, titles):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(writer, "EXCEL_MAX_ROWS", limit + titles + 1)
        parts = split_workbooks("f", [plan(rows, titles)])
    sizes = [p[1][0].n_rows for p in parts]
    assert all(0 < n <= limit for n in sizes)
    assert [v for _, sheets in parts for v in sheets[0].columns[0]] == list(range(rows))


def test_a_row_is_located_in_its_part_and_on_its_worksheet_row(monkeypatch):
    monkeypatch.setattr(writer, "EXCEL_MAX_ROWS", 10)
    parts = split_workbooks("premiums", [plan(25, titles=1)])
    assert locate(parts, 0) == ("premiums_part1.xlsx", 3)  # title row, header row, first row
    assert locate(parts, 6) == ("premiums_part1.xlsx", 9)
    assert locate(parts, 7) == ("premiums_part2.xlsx", 3)
    assert locate(parts, 24) == ("premiums_part4.xlsx", 6)
    with pytest.raises(IndexError):
        locate(parts, 25)


@pytest.fixture(scope="module")
def split_tiny(tmp_path_factory) -> Path:
    """The tiny baseline written with a worksheet of 6000 rows: only the premiums are longer."""
    from actuarycanary.synthetic.build import synthesize

    folder = tmp_path_factory.mktemp("split")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(writer, "EXCEL_MAX_ROWS", 6000)
        synthesize("baseline", "tiny", folder)
    return folder


@pytest.mark.slow
def test_the_frame_check_reads_the_parts_like_one_table(split_tiny):
    from actuarycanary.synthetic.check import check_folder

    assert sorted(p.name for p in split_tiny.glob("premiums*.xlsx")) == [
        "premiums_part1.xlsx",
        "premiums_part2.xlsx",
    ]
    assert check_folder(split_tiny) == check_folder(FIXTURES / "baseline")
    layout = pl.read_csv(split_tiny / "truth" / "layout.csv")
    assert layout.filter(pl.col("file").str.starts_with("premiums"))["data_rows"].sum() == 8031


@pytest.mark.slow
def test_a_run_on_the_parts_gives_the_numbers_of_a_run_on_one_workbook(
    split_tiny, default_run, tmp_path
):
    from actuarycanary.pipeline import run

    parts = run(split_tiny, tmp_path / "out", cache_dir=tmp_path / "cache")
    assert parts.run_id != default_run.run_id  # other input files
    for name in (
        "triangles.csv",
        "factors.csv",
        "chain_ladder.csv",
        "ultimates.csv",
        "reserve_range.csv",
        "measures.csv",
    ):
        # equal to rounding: sums over the premiums add the rows of the parts in another order
        assert_frame_equal(
            pl.read_csv(parts.folder / name),
            pl.read_csv(default_run.folder / name),
            rel_tol=1e-9,
            abs_tol=1e-6,
        )
    used = {i["name"] for i in json.loads(parts.manifest.read_text(encoding="utf-8"))["inputs"]}
    assert {"premiums_part1.xlsx", "premiums_part2.xlsx"} <= used
