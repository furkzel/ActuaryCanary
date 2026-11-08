"""Small helpers for the report pages that read the output tables of a run (records 0340 to
0343): rows of one line, numbers by kind, p-values. The pages read the same tables the run
writes, so every number on them is a cell of a named file."""

import math
from collections.abc import Mapping
from typing import Any

import polars as pl

from actuarycanary.report import numbers

P_FLOOR = 0.001  # p-values below this are shown as "< 0.001"


def table(tables: Mapping[str, pl.DataFrame], name: str) -> pl.DataFrame:
    return tables.get(name, pl.DataFrame())


def of_line(frame: pl.DataFrame, segment: str, line: str) -> list[dict[str, Any]]:
    """The rows of `frame` for one segment and line, in file order."""
    if not frame.height or "segment" not in frame.columns or "line" not in frame.columns:
        return []
    return frame.filter((pl.col("segment") == segment) & (pl.col("line") == line)).to_dicts()


def of_segment(frame: pl.DataFrame, segment: str) -> list[dict[str, Any]]:
    if not frame.height or "segment" not in frame.columns:
        return []
    return frame.filter(pl.col("segment") == segment).to_dicts()


def value(x: Any) -> float | None:
    if x is None or isinstance(x, str | bool):
        return None
    found = float(x)
    return found if math.isfinite(found) else None


def p_value(x: Any) -> str:
    found = value(x)
    if found is None:
        return numbers.EMPTY
    if found < P_FLOOR:
        return f"< {numbers.factor(P_FLOOR)}"
    return numbers.factor(found)


def text(x: Any) -> str:
    return "" if x is None else str(x)
