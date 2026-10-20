"""Day arithmetic on integer day numbers (days since 1970-01-01) with numpy."""

from datetime import date, timedelta

import numpy as np

EPOCH = date(1970, 1, 1)
DAYS_PER_YEAR = 365.25


def to_day(value: date) -> int:
    return (value - EPOCH).days


def from_day(day: int) -> date:
    return EPOCH + timedelta(days=int(day))


def month_index(days: np.ndarray | int) -> np.ndarray:
    """Months since 1970-01 of each day (January 1970 is 0)."""
    return np.asarray(days).astype("datetime64[D]").astype("datetime64[M]").astype(np.int64)


def month_start(months: np.ndarray | int) -> np.ndarray:
    """First day of each month index."""
    return np.asarray(months).astype("datetime64[M]").astype("datetime64[D]").astype(np.int64)


def month_end(months: np.ndarray | int) -> np.ndarray:
    """Last day of each month index."""
    return month_start(np.asarray(months) + 1) - 1


def year_of(days: np.ndarray | int) -> np.ndarray:
    return np.asarray(days).astype("datetime64[D]").astype("datetime64[Y]").astype(np.int64) + 1970


def add_months(days: np.ndarray, months: int) -> np.ndarray:
    """Same day of month `months` later; a day that does not exist moves to the month's last day."""
    stamp = days.astype("datetime64[D]")
    month = stamp.astype("datetime64[M]")
    day_of_month = (stamp - month.astype("datetime64[D]")).astype(np.int64)
    target = month + np.timedelta64(months, "M")
    length = (target + np.timedelta64(1, "M")).astype("datetime64[D]") - target.astype(
        "datetime64[D]"
    )
    day = np.minimum(day_of_month, length.astype(np.int64) - 1)
    return target.astype("datetime64[D]").astype(np.int64) + day


def years_since(days: np.ndarray, base_day: int) -> np.ndarray:
    return (np.asarray(days, dtype=np.float64) - base_day) / DAYS_PER_YEAR
