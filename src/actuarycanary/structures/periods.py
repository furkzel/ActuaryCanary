"""Periods, month indices and labels (CV04)."""

import calendar
from datetime import date
from enum import StrEnum


class Period(StrEnum):
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    HALF = "HALF"
    YEAR = "YEAR"

    @property
    def months(self) -> int:
        return {"MONTH": 1, "QUARTER": 3, "HALF": 6, "YEAR": 12}[self.value]


def month_index(day: date) -> int:
    """m(t) = 12 year + month - 1."""
    return 12 * day.year + day.month - 1


def month_end(index: int) -> date:
    year, month = divmod(index, 12)
    return date(year, month + 1, calendar.monthrange(year, month + 1)[1])


def period_start(index: int, period: Period, fiscal_start: int = 1) -> int:
    """Month index of the first month of the period that contains month `index`."""
    offset = fiscal_start - 1
    return (index - offset) // period.months * period.months + offset


def period_label(start: int, period: Period, fiscal_start: int = 1) -> str:
    """YYYY, YYYY-Hn or YYYY-Qn in the fiscal year in which the period starts; months YYYY-MM."""
    fiscal_year_start = period_start(start, Period.YEAR, fiscal_start)
    year = fiscal_year_start // 12
    position = (start - fiscal_year_start) // period.months + 1
    match period:
        case Period.YEAR:
            return f"{year}"
        case Period.HALF:
            return f"{year}-H{position}"
        case Period.QUARTER:
            return f"{year}-Q{position}"
        case Period.MONTH:  # a month keeps its calendar name
            return f"{start // 12}-{start % 12 + 1:02d}"
