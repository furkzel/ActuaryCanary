"""Claim sizes by group for the severity methods (MT17, MT18).

The input is one row per claim with its size already converted and restated as CV08 does it
(reporting currency, constant development rate, value-date prices): columns `claim_id`,
`size`, `status`, and optionally `segment`, `line`, `event_code` and `origin_year`. A missing
segment or line is UNKNOWN. Rows are sorted by claim_id before anything is drawn or fitted, so
results depend on the data and the seed, never on row order.
"""

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl

from actuarycanary.methods.severity.numeric import log_linear_trend

GROUP_BY = ("segment", "line")
UNKNOWN = "UNKNOWN"
NIL = "CLOSED_NIL"
CLOSED = "CLOSED"
CLOSED_CLAIMS, ALL_NON_NIL = "closed", "all_non_nil"
CLAIMS_USED = (CLOSED_CLAIMS, ALL_NON_NIL)
SEED = 1  # run seed of the severity methods; recorded with every result
MIN_YEARS_FOR_TREND = 3
MIN_CLAIMS_FOR_TREND = 10
TREND_SIGNIFICANCE = 0.01

Key = tuple[str, ...]


@dataclass(frozen=True)
class GroupSizes:
    key: Key
    sizes: np.ndarray  # ascending claim_id order
    years: np.ndarray  # origin year per size, NaN when unknown
    n_events: int = 0  # sizes that are catastrophe events (one size per event)

    @property
    def label(self) -> str:
        return " / ".join(self.key)


def group_rng(seed: int, key: Key, stream: int = 0) -> np.random.Generator:
    """A generator of its own for a group and a purpose: independent of the order of groups."""
    return np.random.default_rng(
        np.random.SeedSequence([seed, zlib.crc32("|".join(key).encode("utf-8")), stream])
    )


def _normalised(frame: pl.DataFrame, group_by: Sequence[str]) -> pl.DataFrame:
    for needed in ("claim_id", "size", "status"):
        if needed not in frame.columns:
            raise ValueError(f"claim sizes need a column {needed!r}")
    rows = frame
    for column, dtype in (("event_code", pl.String), ("origin_year", pl.Int64)):
        if column not in rows.columns:
            rows = rows.with_columns(pl.lit(None, dtype).alias(column))
    rows = rows.with_columns(
        [
            pl.col(g).fill_null(UNKNOWN) if g in rows.columns else pl.lit(UNKNOWN).alias(g)
            for g in group_by
        ]
    )
    return rows.sort("claim_id")


def group_sizes(
    frame: pl.DataFrame,
    *,
    claims_used: str = CLOSED_CLAIMS,
    catastrophes: str = "exclude",
    group_by: Sequence[str] = GROUP_BY,
) -> list[GroupSizes]:
    """The sizes of each group.

    Nil claims (status CLOSED_NIL, or a size of zero) are never used. `claims_used` "closed"
    keeps closed non-nil claims (final sizes), "all_non_nil" keeps every non-nil claim at its
    incurred. A claim with an event code is a catastrophe claim: `catastrophes` "exclude"
    drops it (MT17), "events" replaces the claims of an event by one size, their sum (MT18),
    "keep" treats it as any other claim."""
    if claims_used not in CLAIMS_USED:
        raise ValueError(f"claims_used {claims_used!r}: allowed {', '.join(CLAIMS_USED)}")
    if catastrophes not in ("exclude", "events", "keep"):
        raise ValueError(f"catastrophes {catastrophes!r}: allowed exclude, events, keep")
    rows = _normalised(frame, group_by)
    keep = (pl.col("status") != NIL) & (pl.col("size") > 0) & pl.col("size").is_not_null()
    if claims_used == CLOSED_CLAIMS:
        keep &= pl.col("status") == CLOSED
    rows = rows.filter(keep)
    event = pl.col("event_code").is_not_null() & ~pl.col("event_code").is_in(["", UNKNOWN])
    ordinary = (rows if catastrophes == "keep" else rows.filter(~event)).with_columns(
        pl.lit(False).alias("is_event")
    )
    if catastrophes == "events":
        events = (
            rows.filter(event)
            .group_by([*group_by, "event_code"])
            .agg(
                pl.col("size").sum(),
                pl.col("origin_year").min(),
                pl.col("claim_id").min(),
            )
            .with_columns(pl.lit(True).alias("is_event"))
        )
        ordinary = pl.concat(
            [
                ordinary.select(*group_by, "claim_id", "size", "origin_year", "is_event"),
                events.select(*group_by, "claim_id", "size", "origin_year", "is_event"),
            ]
        ).sort("claim_id")
    groups: list[GroupSizes] = []
    for key, part in ordinary.group_by(list(group_by), maintain_order=True):
        years = part["origin_year"].cast(pl.Float64).fill_null(float("nan")).to_numpy()
        groups.append(
            GroupSizes(
                tuple(str(k) for k in key),
                part["size"].to_numpy().astype(np.float64),
                years,
                int(part["is_event"].sum()),
            )
        )
    return sorted(groups, key=lambda g: g.key)


def severity_trend(sizes: np.ndarray, years: np.ndarray) -> tuple[pl.DataFrame, dict[str, float]]:
    """Sizes by origin year at value-date prices and their log-linear trend (MT17 assumption:
    no trend, a trend means superimposed inflation). Returns the table by year (claims, mean,
    median) and the regression of ln(size) on the year: annual change, its standard error and
    p-value, NaN when fewer than three years or ten claims have a year."""
    known = np.isfinite(years)
    table = pl.DataFrame({"origin_year": years[known].astype(np.int64), "size": sizes[known]})
    by_year = (
        table.group_by("origin_year")
        .agg(
            pl.len().alias("claims"),
            pl.col("size").mean().alias("mean"),
            pl.col("size").median().alias("median"),
        )
        .sort("origin_year")
        if table.height
        else pl.DataFrame(
            schema={
                "origin_year": pl.Int64,
                "claims": pl.UInt32,
                "mean": pl.Float64,
                "median": pl.Float64,
            }
        )
    )
    summary = {"annual_change": math.nan, "standard_error": math.nan, "p_value": math.nan}
    if by_year.height >= MIN_YEARS_FOR_TREND and table.height >= MIN_CLAIMS_FOR_TREND:
        x = years[known]
        slope, error, p_value = log_linear_trend(x, np.log(sizes[known]))
        summary = {
            "annual_change": math.expm1(slope),
            "standard_error": error,
            "p_value": p_value,
        }
    return by_year, summary
