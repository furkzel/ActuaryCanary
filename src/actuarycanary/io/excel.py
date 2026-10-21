"""Reads a spreadsheet once into polars (calamine engine) and caches every sheet as parquet.

The cache is keyed by the SHA-256 fingerprint of the file content and the reader version, so
a renamed copy of the same file is read from the cache and a changed file is read again.
Every row carries its source file name, sheet name and spreadsheet row number.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

# Raise when the way values are read changes, so cached tables are read again.
READER_VERSION = 1

SOURCE_FILE = "_source_file"
SOURCE_SHEET = "_source_sheet"
SOURCE_ROW = "_source_row"
SOURCE_COLUMNS = (SOURCE_FILE, SOURCE_SHEET, SOURCE_ROW)

HEADER_ROW = 1  # spreadsheet row of the header; recognition of other header rows is later work

_CHUNK = 1 << 20


@dataclass(frozen=True)
class RawTable:
    """One sheet as read, values unchanged, plus the three source columns."""

    sheet: str
    frame: pl.DataFrame


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


def _read_sheets(path: Path) -> dict[str, pl.DataFrame]:
    sheets = pl.read_excel(
        path,
        sheet_id=0,  # every sheet
        engine="calamine",
        infer_schema_length=None,  # infer each column's type from all of its cells
        drop_empty_rows=False,  # keep row positions so row numbers stay true
        drop_empty_cols=False,
        raise_if_empty=False,
    )
    return {
        name: frame.with_row_index(SOURCE_ROW, offset=HEADER_ROW + 1).with_columns(
            pl.col(SOURCE_ROW).cast(pl.Int64)
        )
        for name, frame in sheets.items()
    }


def _cache_folder(cache_dir: Path, sha256: str) -> Path:
    return cache_dir / "io" / f"{sha256}-r{READER_VERSION}"


def _load_cached(folder: Path) -> dict[str, pl.DataFrame] | None:
    index = folder / "sheets.json"
    if not index.is_file():
        return None
    names: list[str] = json.loads(index.read_text(encoding="utf-8"))
    return {name: pl.read_parquet(folder / f"{n}.parquet") for n, name in enumerate(names)}


def _store(folder: Path, sheets: dict[str, pl.DataFrame]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for n, frame in enumerate(sheets.values()):
        frame.write_parquet(folder / f"{n}.parquet")
    # written last: a folder without its index is incomplete and is read again
    (folder / "sheets.json").write_text(json.dumps(list(sheets)), encoding="utf-8")


def read_workbook(path: Path, cache_dir: Path | None) -> Workbook:
    """Read every sheet of `path`; use and fill the parquet cache when `cache_dir` is given."""
    sha256 = file_sha256(path)
    sheets: dict[str, pl.DataFrame] | None = None
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
        )
        for name, frame in sheets.items()
    )
    return Workbook(path, sha256, path.stat().st_size, tables)
