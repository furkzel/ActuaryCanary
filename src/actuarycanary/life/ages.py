"""Ages and policy years by policy anniversaries (CV11, record 0445). Birth dates are never read.

Dates are day numbers (days since 1970-01-01, int64 numpy arrays), so that every step works on
whole columns at once.

- An anniversary is the same day of the month whole years after entry; a day that the month
  lacks (29 February) falls on the month's last day.
- Whole policy years completed at day t: the anniversaries of entry on or before t.
- Policy year at t: whole years + 1 (the first year is policy year 1).
- Entry age: the lower age of the first valuation's age_band minus the whole policy years from
  entry to that valuation (a band "x-y" and an open band "x+" use x). Attained age at t: entry
  age + whole policy years at t, so age and policy year move together on the anniversary.
- `age_last_birthday` and `age_nearest_birthday` give the same numbers: the definition says what
  the source's ages mean, and the outputs name it (the label of the age column and the manifest).
- The age band of the outputs: `age_band_width` years from a multiple of the width ("45-49"),
  one age for a width of 1; a source band wider than the width keeps its own width, moved with
  the years ("40-49" ten years later is "50-59"), and an open band stays open ("85+").
"""

import numpy as np
import polars as pl

AGE_DEFINITIONS = ("age_last_birthday", "age_nearest_birthday")


def to_days(dates: pl.Series) -> np.ndarray:
    return dates.cast(pl.Date).cast(pl.Int64).to_numpy()


def shift_years(days: np.ndarray, years: np.ndarray | int) -> np.ndarray:
    """The same day of the month `years` later, clamped to the month's last day."""
    stamp = np.asarray(days, dtype=np.int64).astype("datetime64[D]")
    month = stamp.astype("datetime64[M]")
    day_of_month = (stamp - month.astype("datetime64[D]")).astype(np.int64)
    target = month + (12 * np.asarray(years, dtype=np.int64)).astype("timedelta64[M]")
    length = (target + np.timedelta64(1, "M")).astype("datetime64[D]") - target.astype(
        "datetime64[D]"
    )
    day = np.minimum(day_of_month, length.astype(np.int64) - 1)
    return target.astype("datetime64[D]").astype(np.int64) + day


def year_of(days: np.ndarray) -> np.ndarray:
    return (
        np.asarray(days, dtype=np.int64)
        .astype("datetime64[D]")
        .astype("datetime64[Y]")
        .astype(np.int64)
        + 1970
    )


def jan1(years: np.ndarray) -> np.ndarray:
    """Day number of 1 January of each year."""
    return (
        (np.asarray(years, dtype=np.int64) - 1970)
        .astype("datetime64[Y]")
        .astype("datetime64[D]")
        .astype(np.int64)
    )


def whole_years(entry: np.ndarray, day: np.ndarray) -> np.ndarray:
    """Whole policy years completed at `day`: anniversaries of `entry` on or before it."""
    guess = year_of(day) - year_of(entry)
    return guess - (shift_years(entry, guess) > np.asarray(day)).astype(np.int64)


def policy_year(entry: np.ndarray, day: np.ndarray) -> np.ndarray:
    return whole_years(entry, day) + 1


def entry_age(entry: np.ndarray, first_valuation: np.ndarray, age_at_first: np.ndarray):
    """Entry age from the age (lower age of the band) at the first valuation."""
    return np.asarray(age_at_first, dtype=np.int64) - whole_years(entry, first_valuation)


def attained_age(entry: np.ndarray, age_at_entry: np.ndarray, day: np.ndarray) -> np.ndarray:
    return np.asarray(age_at_entry, dtype=np.int64) + whole_years(entry, day)


def band_expr(age: pl.Expr, width: int, source_width: pl.Expr, open_band: pl.Expr) -> pl.Expr:
    """The output age band of `age`: see the module docstring. `source_width` is the width of
    the contract's source band (1 for a single age), `open_band` whether it is "x+"."""
    low = (age // width) * width
    own = age.cast(pl.String) if width == 1 else pl.format("{}-{}", low, low + width - 1)
    wider = pl.format("{}-{}", age, age + source_width - 1)
    return (
        pl.when(open_band)
        .then(pl.format("{}+", age))
        .when(source_width > width)
        .then(wider)
        .otherwise(own)
    )
