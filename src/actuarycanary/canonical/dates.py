"""Dates given as text: the formats a column uses are found from its values, then parsed.

Spreadsheet cells that mix real dates and text are read as text for the whole column (record
0017); a real date then arrives as ``2022-01-31 00:00:00``. Day-first and month-first slash
dates are told apart by values above 12; when no value decides, day-first is used, which is
the Turkish convention, and the evidence says so (record 0027).
"""

from dataclasses import dataclass

import polars as pl

ISO_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S")
DAY_FIRST = ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y")
MONTH_FIRST = ("%m/%d/%Y",)

_DAY_MONTH = r"^\s*(\d{1,2})[./-](\d{1,2})[./-]\d{4}\s*$"


@dataclass(frozen=True)
class DateParse:
    values: pl.Series  # pl.Date; null where the text is not a date in any chosen format
    formats: tuple[str, ...]  # formats that matched at least one value
    note: str  # how day and month order was decided, when it had to be


def _order(text: pl.Series) -> tuple[tuple[str, ...], str]:
    groups = text.str.extract_groups(_DAY_MONTH)
    first = groups.struct.field("1").cast(pl.Int32, strict=False)
    second = groups.struct.field("2").cast(pl.Int32, strict=False)
    if first.is_null().all():
        return DAY_FIRST, ""
    if (first > 12).any():
        return DAY_FIRST, "day first: some first parts exceed 12"
    if (second > 12).any():
        return MONTH_FIRST, "month first: some second parts exceed 12"
    return DAY_FIRST, "day and month order undecided by the values; day first assumed"


def parse_dates(series: pl.Series) -> DateParse:
    """`series` as dates: Date kept, Datetime truncated, text parsed; anything else is empty."""
    if series.dtype == pl.Date:
        return DateParse(series, (), "")
    if series.dtype == pl.Datetime:
        return DateParse(series.dt.date(), (), "")
    if series.dtype != pl.String:
        return DateParse(pl.Series(series.name, [None] * series.len(), dtype=pl.Date), (), "")
    text = series.str.strip_chars()
    ordered, note = _order(text)
    result = pl.Series(series.name, [None] * series.len(), dtype=pl.Date)
    used: list[str] = []
    for fmt in (*ISO_FORMATS, *ordered):
        parsed = text.str.strptime(pl.Datetime, fmt, strict=False).dt.date()
        fills = result.is_null() & parsed.is_not_null()
        if fills.any():
            used.append(fmt)
            result = parsed.zip_with(fills, result)
    return DateParse(result.alias(series.name), tuple(used), note)
