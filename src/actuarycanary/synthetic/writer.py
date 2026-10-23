"""Writing worksheets (xlsxwriter), parquet and the small truth files. Output is deterministic:
the same inputs give the same bytes."""

import hashlib
import zipfile
from datetime import datetime
from pathlib import Path

import polars as pl
import xlsxwriter

from actuarycanary.synthetic.messy import SheetPlan

EXCEL_MAX_ROWS = 1_048_576
FIXED_TIMESTAMP = datetime(2026, 1, 1)  # workbook properties would otherwise carry the clock


def _rows_per_part(sheet: SheetPlan) -> int:
    return EXCEL_MAX_ROWS - len(sheet.title_rows) - 1


def split_workbooks(feed: str, sheets: list[SheetPlan]) -> list[tuple[str, list[SheetPlan]]]:
    """The workbooks of one feed: `<feed>.xlsx` when every sheet fits in a worksheet, otherwise
    `<feed>_part1.xlsx`, `<feed>_part2.xlsx`, ... of nearly equal size, each with the same
    sheet names, title rows and header row, and consecutive rows of the table (record 0081)."""
    parts = max(-(-s.n_rows // _rows_per_part(s)) for s in sheets)
    if parts <= 1:
        return [(f"{feed}.xlsx", sheets)]
    workbooks: list[tuple[str, list[SheetPlan]]] = []
    for k in range(parts):
        chunks: list[SheetPlan] = []
        for s in sheets:
            size = -(-s.n_rows // parts)
            chunk = [column[k * size : (k + 1) * size] for column in s.columns]
            chunks.append(SheetPlan(s.name, s.title_rows, s.headers, chunk))
        workbooks.append((f"{feed}_part{k + 1}.xlsx", chunks))
    return workbooks


def write_workbook(path: Path, sheets: list[SheetPlan]) -> None:
    """One workbook; each sheet is title rows, a header row and the data rows."""
    workbook = xlsxwriter.Workbook(
        str(path),
        {
            "constant_memory": True,
            "default_date_format": "yyyy-mm-dd",
            "strings_to_numbers": False,  # keep identifiers such as 00001234 as text
            "strings_to_formulas": False,
            "strings_to_urls": False,
            "nan_inf_to_errors": True,
        },
    )
    workbook.set_properties({"created": FIXED_TIMESTAMP, "title": path.stem})
    for sheet in sheets:
        worksheet = workbook.add_worksheet(sheet.name)
        row = 0
        for title in sheet.title_rows:
            if title:
                worksheet.write_row(row, 0, title)
            row += 1
        worksheet.write_row(row, 0, sheet.headers)
        row += 1
        for values in zip(*sheet.columns, strict=True):
            worksheet.write_row(row, 0, values)
            row += 1
    workbook.close()


def write_parquet(path: Path, frame: pl.DataFrame) -> None:
    frame.write_parquet(path, compression="zstd", statistics=False)


def write_csv(path: Path, frame: pl.DataFrame) -> None:
    frame.write_csv(path, float_precision=6)


def sha256(path: Path) -> str:
    """SHA-256 of a file. For a workbook it is taken over the uncompressed parts of the
    archive, so it does not depend on the compression library of the machine."""
    digest = hashlib.sha256()
    if path.suffix == ".xlsx":
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                digest.update(name.encode())
                digest.update(archive.read(name))
        return digest.hexdigest()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
