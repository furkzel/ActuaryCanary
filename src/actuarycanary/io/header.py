"""Finds the header row of a sheet from its first rows, read as text without a header.

Blueprint section 6.1: the header is the first row whose cells are mostly distinct text above
rows of typed values (numbers and dates); title, note and blank rows above it are skipped.
When no row has typed values below it (an all-text table), the first row that is wide,
textual and distinct is taken. The choice and its evidence are recorded.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

Row = Sequence[str | None]

_NUMBER = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(
    r"^(\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?"
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})$"
)
MIN_FILL = 0.5  # share of the table width a header row fills
MIN_TEXT = 0.8  # share of a header row's cells that are text, not numbers or dates
MIN_DISTINCT = 0.9  # share of a header row's cells that are distinct
LOOK_BELOW = 3  # non-empty rows below a candidate that are checked for typed values


@dataclass(frozen=True)
class HeaderRow:
    index: int  # 0-based position in the rows given, which start at spreadsheet row 1
    rows_above: int  # non-empty rows above the header (titles, notes)
    evidence: str

    @property
    def row(self) -> int:
        """1-based spreadsheet row of the header."""
        return self.index + 1


def _cell(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def is_typed(value: str) -> bool:
    """A number or a date written as text by the reader."""
    return bool(_NUMBER.match(value) or _DATE.match(value))


def _cells(row: Row) -> list[str]:
    return [c for c in (_cell(v) for v in row) if c is not None]


def _header_like(cells: list[str], width: int) -> bool:
    if len(cells) < max(2, math.ceil(MIN_FILL * width)):
        return False
    text = sum(not is_typed(c) for c in cells)
    distinct = len({c.casefold() for c in cells})
    return text >= MIN_TEXT * len(cells) and distinct >= MIN_DISTINCT * len(cells)


def _typed_below(rows: list[list[str]], start: int, width: int) -> bool:
    """The next non-empty row is data, not another header-like row, and typed values follow."""
    below = [cells for cells in rows[start + 1 :] if cells][:LOOK_BELOW]
    if not below:
        return False
    following = below[0]
    if _header_like(following, width) and not any(is_typed(c) for c in following):
        return False
    return any(is_typed(c) for cells in below for c in cells)


def find_header(rows: Sequence[Row]) -> HeaderRow:
    """The header row among `rows` (the first rows of a sheet, from spreadsheet row 1)."""
    cells = [_cells(r) for r in rows]
    width = max((len(c) for c in cells), default=0)
    if width == 0:
        return HeaderRow(0, 0, "empty sheet")
    candidates = [i for i, c in enumerate(cells) if _header_like(c, width)]
    for i in candidates:
        if _typed_below(cells, i, width):
            above = sum(1 for c in cells[:i] if c)
            return HeaderRow(
                i,
                above,
                f"row {i + 1}: {len(cells[i])} of {width} columns named, typed values below"
                + (f"; {above} row(s) above skipped" if above else ""),
            )
    if candidates:
        i = candidates[0]
        above = sum(1 for c in cells[:i] if c)
        return HeaderRow(
            i, above, f"row {i + 1}: first row of distinct text; no typed values below it"
        )
    first = next(i for i, c in enumerate(cells) if c)
    return HeaderRow(first, 0, f"row {first + 1}: no row looks like a header; first non-empty row")
