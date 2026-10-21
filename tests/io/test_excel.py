"""Reader: one read per file content, parquet cache keyed by SHA-256, source rows kept."""

import shutil
from pathlib import Path

import polars as pl
import pytest
import xlsxwriter

from actuarycanary.io.excel import (
    READER_VERSION,
    SOURCE_FILE,
    SOURCE_ROW,
    SOURCE_SHEET,
    file_sha256,
    read_workbook,
    spreadsheets,
)

BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"

pytestmark = pytest.mark.integration


def test_reads_every_row_with_its_source(tmp_path: Path) -> None:
    workbook = read_workbook(BASELINE / "claim_valuations.xlsx", tmp_path)
    table = workbook.table()
    assert table.sheet == "claim_valuations"
    assert table.frame.height == 1242  # rows in the fixture manifest
    assert table.frame[SOURCE_FILE].unique().to_list() == ["claim_valuations.xlsx"]
    assert table.frame[SOURCE_SHEET].unique().to_list() == ["claim_valuations"]
    assert table.frame[SOURCE_ROW].to_list() == list(range(2, 1244))  # header on row 1


def test_row_numbers_match_the_spreadsheet(tmp_path: Path) -> None:
    faults = pl.read_csv(BASELINE / "truth" / "injected_faults.csv").filter(
        pl.col("fault_type") == "missing_currency"
    )
    frame = read_workbook(BASELINE / "claim_valuations.xlsx", tmp_path).table().frame
    for key, sheet_row in faults.select("key", "sheet_row").iter_rows():
        claim_id, valuation_date = key.split("|")
        row = frame.filter(pl.col(SOURCE_ROW) == sheet_row).row(0, named=True)
        assert row["claim_id"] == claim_id
        assert row["valuation_date"].isoformat() == valuation_date
        assert row["currency"] is None  # the reader never fills or changes a value


def test_second_read_comes_from_the_cache_keyed_by_content(tmp_path: Path) -> None:
    source = BASELINE / "claims.xlsx"
    cache = tmp_path / "cache"
    first = read_workbook(source, cache)
    folder = cache / "io" / f"{file_sha256(source)}-r{READER_VERSION}"
    assert (folder / "sheets.json").is_file()

    renamed = tmp_path / "renamed.xlsx"
    shutil.copyfile(source, renamed)
    second = read_workbook(renamed, cache)
    assert second.sha256 == first.sha256
    assert len(list((cache / "io").iterdir())) == 1  # same content, same cache entry
    expected = first.table().frame.drop(SOURCE_FILE)
    assert second.table().frame.drop(SOURCE_FILE).equals(expected)
    assert second.table().frame[SOURCE_FILE].unique().to_list() == ["renamed.xlsx"]


def test_cache_is_optional(tmp_path: Path) -> None:
    uncached = read_workbook(BASELINE / "claims.xlsx", None)
    cached = read_workbook(BASELINE / "claims.xlsx", tmp_path)
    assert uncached.table().frame.equals(cached.table().frame)
    assert uncached.size == (BASELINE / "claims.xlsx").stat().st_size


MESSY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "messy_headers"


def test_header_row_is_found_below_title_rows(tmp_path: Path) -> None:
    table = read_workbook(MESSY / "claim_valuations.xlsx", tmp_path).table()
    assert (table.header_row, table.rows_above) == (4, 3)  # truth/layout.csv
    assert "HASARR NO " in table.headers  # header text kept exactly as written
    assert table.frame[SOURCE_ROW][0] == 5
    assert table.frame["OS RSERVE"].dtype == pl.Float64  # typed from the header row down


def test_rows_keep_spreadsheet_numbers_after_blank_and_title_rows(tmp_path: Path) -> None:
    path = tmp_path / "blank.xlsx"
    with xlsxwriter.Workbook(path) as book:
        sheet = book.add_worksheet("Veri")
        sheet.write(2, 1, "Hasar listesi")  # row 3, column B: a title below two blank rows
        sheet.write_row(4, 1, ["Hasar No", "Ödenen", "Durum"])  # header on row 5
        sheet.write_row(5, 1, ["0001", 10.5, "AÇIK"])
        sheet.write_row(7, 1, ["0002", 3.0, "KAPALI"])  # row 8, after a blank row 7
    table = read_workbook(path, tmp_path / "cache").table()
    assert (table.header_row, table.rows_above) == (5, 1)
    assert table.headers == ("Hasar No", "Ödenen", "Durum")
    rows = table.frame.filter(pl.col("Hasar No").is_not_null())
    assert rows[SOURCE_ROW].to_list() == [6, 8]
    assert rows["Ödenen"].to_list() == [10.5, 3.0]


def test_spreadsheets_in_a_folder_skip_lock_files(tmp_path: Path) -> None:
    for name in ("b.xlsx", "a.XLSX", "~$a.xlsx", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in spreadsheets(tmp_path)] == ["a.XLSX", "b.xlsx"]
