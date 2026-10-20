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


def fits_in_worksheet(sheet: SheetPlan) -> bool:
    return len(sheet.title_rows) + 1 + sheet.n_rows <= EXCEL_MAX_ROWS


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
