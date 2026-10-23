"""Reads a spreadsheet once into polars (calamine engine) and caches every sheet as parquet.

The first rows of every sheet are read as text to find the header row (io.header); the sheet
is then read with types from that row. The cache is keyed by the SHA-256 fingerprint of the
file content and the reader version, so a renamed copy of the same file is read from the
cache and a changed file is read again. Every row carries its source file name, sheet name
and spreadsheet row number.
"""

import hashlib
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from actuarycanary.io.header import HeaderRow, find_header

# Raise when the way values are read changes, so cached tables are read again.
READER_VERSION = 2

SOURCE_FILE = "_source_file"
SOURCE_SHEET = "_source_sheet"
SOURCE_ROW = "_source_row"
SOURCE_COLUMNS = (SOURCE_FILE, SOURCE_SHEET, SOURCE_ROW)

READ_WORKERS = 6  # files read at once; every one holds its sheet in memory while it is parsed
PROBE_ROWS = 50  # rows read as text to find the header
SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".ods")

_CHUNK = 1 << 20


@dataclass(frozen=True)
class RawTable:
    """One sheet as read, values unchanged, plus the three source columns."""

    sheet: str
    frame: pl.DataFrame
    header_row: int = 1  # 1-based spreadsheet row of the header
    rows_above: int = 0  # non-empty rows above the header (titles, notes), skipped
    header_evidence: str = ""

    @property
    def headers(self) -> tuple[str, ...]:
        """Column names as written in the header row, in sheet order."""
        return tuple(c for c in self.frame.columns if c not in SOURCE_COLUMNS)


@dataclass(frozen=True)
class Workbook:
    path: Path
    sha256: str
    size: int
    tables: tuple[RawTable, ...]

    @property
    def name(self) -> str:
        return self.path.name

    def table(self, sheet: str | None = None) -> RawTable:
        """The named sheet, or the first sheet when no name is given."""
        if sheet is None:
            return self.tables[0]
        for table in self.tables:
            if table.sheet == sheet:
                return table
        raise KeyError(f"{self.name} has no sheet {sheet!r}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


_COMMON: dict[str, Any] = {
    "engine": "calamine",
    "drop_empty_rows": False,  # keep row positions so row numbers stay true
    "drop_empty_cols": False,
    "raise_if_empty": False,
}


def _probe(path: Path) -> dict[str, list[tuple[str | None, ...]]]:
    """The first rows of every sheet as text, from spreadsheet row 1 (no rows skipped)."""
    sheets = pl.read_excel(
        path,
        sheet_id=0,  # every sheet
        has_header=False,
        read_options={"header_row": None, "skip_rows": 0, "n_rows": PROBE_ROWS},
        infer_schema_length=None,
        **_COMMON,
    )
    return {name: frame.cast(pl.String).rows() for name, frame in sheets.items()}


def _read_sheet(path: Path, sheet: str, header: HeaderRow) -> pl.DataFrame:
    frame = pl.read_excel(
        path,
        sheet_name=sheet,
        # header_row counts from spreadsheet row 1 when no rows are skipped
        read_options={"header_row": header.index, "skip_rows": 0},
        infer_schema_length=None,  # infer each column's type from all of its cells
        **_COMMON,
    )
    return frame.with_row_index(SOURCE_ROW, offset=header.row + 1).with_columns(
        pl.col(SOURCE_ROW).cast(pl.Int64)
    )


def _read_sheets(path: Path) -> dict[str, tuple[pl.DataFrame, HeaderRow]]:
    sheets: dict[str, tuple[pl.DataFrame, HeaderRow]] = {}
    for name, rows in _probe(path).items():
        header = find_header(rows)
        if not rows:
            sheets[name] = (pl.DataFrame({SOURCE_ROW: []}, schema={SOURCE_ROW: pl.Int64}), header)
            continue
        sheets[name] = (_read_sheet(path, name, header), header)
    return sheets


def _cache_folder(cache_dir: Path, sha256: str) -> Path:
    return cache_dir / "io" / f"{sha256}-r{READER_VERSION}"


def _load_cached(folder: Path) -> dict[str, tuple[pl.DataFrame, HeaderRow]] | None:
    index = folder / "sheets.json"
    if not index.is_file():
        return None
    entries: list[dict[str, Any]] = json.loads(index.read_text(encoding="utf-8"))
    return {
        e["name"]: (
            pl.read_parquet(folder / f"{n}.parquet"),
            HeaderRow(e["header_index"], e["rows_above"], e["evidence"]),
        )
        for n, e in enumerate(entries)
    }


def _store(folder: Path, sheets: dict[str, tuple[pl.DataFrame, HeaderRow]]) -> None:
    """Write into a private folder, then rename it into place, so that processes reading the
    same file at the same time never see a half-written entry."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{folder.name}.", dir=folder.parent))
    entries: list[dict[str, Any]] = []
    for n, (name, (frame, header)) in enumerate(sheets.items()):
        frame.write_parquet(work / f"{n}.parquet")
        entries.append(
            {
                "name": name,
                "header_index": header.index,
                "rows_above": header.rows_above,
                "evidence": header.evidence,
            }
        )
    (work / "sheets.json").write_text(json.dumps(entries), encoding="utf-8")
    try:
        work.rename(folder)
    except OSError:  # another process stored the same content first
        shutil.rmtree(work, ignore_errors=True)


def read_workbook(path: Path, cache_dir: Path | None) -> Workbook:
    """Read every sheet of `path`; use and fill the parquet cache when `cache_dir` is given."""
    sha256 = file_sha256(path)
    sheets: dict[str, tuple[pl.DataFrame, HeaderRow]] | None = None
    if cache_dir is not None:
        folder = _cache_folder(cache_dir, sha256)
        sheets = _load_cached(folder)
        if sheets is None:
            sheets = _read_sheets(path)
            _store(folder, sheets)
    else:
        sheets = _read_sheets(path)
    tables = tuple(
        RawTable(
            name,
            frame.with_columns(
                pl.lit(path.name).alias(SOURCE_FILE), pl.lit(name).alias(SOURCE_SHEET)
            ),
            header.row,
            header.rows_above,
            header.evidence,
        )
        for name, (frame, header) in sheets.items()
    )
    return Workbook(path, sha256, path.stat().st_size, tables)


def read_workbooks(paths: list[Path], cache_dir: Path | None) -> list[Workbook]:
    """`read_workbook` for each of `paths`, several at a time (the parser releases the GIL);
    the result is in the order of `paths`, and the first failure in that order is raised."""
    workers = min(READ_WORKERS, os.cpu_count() or 1, len(paths))
    if workers <= 1:
        return [read_workbook(path, cache_dir) for path in paths]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda path: read_workbook(path, cache_dir), paths))


def spreadsheets(folder: Path) -> list[Path]:
    """Spreadsheet files directly in `folder`, by name; lock files of open workbooks skipped."""
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SPREADSHEET_SUFFIXES and not p.name.startswith("~$")
    )
