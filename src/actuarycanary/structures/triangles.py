"""Development triangles from claim valuations (MT01, CV04).

A claim's state at a valuation point is its latest row on or before that point
(carry-forward). Each claim contributes, at every valuation point, the change of its as-of
amount since the previous point; summing these changes per origin and point and
accumulating along the row gives the cumulative triangle with carry-forward built in.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from actuarycanary.canonical.feeds import Finding, finding
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import Period, month_end, month_index, period_label

MEASURES = ("paid", "incurred")
GROUP_FIELDS = ("segment", "line")
UNKNOWN = "UNKNOWN"
THIN_CELL_CLAIMS = 5  # MT01 diagnostic: cells with fewer contributing claims are thin


class TriangleError(Exception):
    """The triangles cannot be built from the data given (MT01 failure modes)."""


class OriginAxis(StrEnum):
    ACCIDENT = "accident"
    REPORT = "report"
    FIRST_VALUATION = "first_valuation"


_ORIGIN_FIELD = {OriginAxis.ACCIDENT: "occurrence_date", OriginAxis.REPORT: "report_date"}


class TriangleSettings(BaseModel):
    """MT01 parameters used in this version; the reinsurance basis is GROSS, value NOMINAL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    origin_period: Period = Period.YEAR
    development_period: Period = Period.YEAR
    origin_axis: OriginAxis = OriginAxis.ACCIDENT
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    cut_off: date | None = None  # None: the latest valuation_date (CV04)

    @model_validator(mode="after")
    def _whole_multiple(self) -> "TriangleSettings":
        if self.origin_period.months % self.development_period.months:
            allowed = [p.value for p in Period if p.months <= self.origin_period.months]
            allowed = [p for p in allowed if self.origin_period.months % Period(p).months == 0]
            raise ValueError(
                f"origin period {self.origin_period.value} is not a whole multiple of "
                f"development period {self.development_period.value}; allowed development "
                f"periods: {', '.join(allowed)}"
            )
        return self


@dataclass(frozen=True)
class Triangle:
    """One measure for one group: origins down, development ages (months) across."""

    measure: str
    group: tuple[str, ...]  # values of GROUP_FIELDS
    origins: tuple[str, ...]
    ages: tuple[int, ...]
    cumulative: np.ndarray  # float, NaN where the cell lies after the cut-off
    claim_counts: np.ndarray  # reported claims per cell, -1 where the cell is not observed
    calendar: np.ndarray  # index of the cell's valuation point, -1 where not observed
    valuation_points: tuple[date, ...]

    @property
    def observed(self) -> np.ndarray:
        return ~np.isnan(self.cumulative)

    @property
    def incremental(self) -> np.ndarray:
        incremental = self.cumulative.copy()
        incremental[:, 1:] = self.cumulative[:, 1:] - self.cumulative[:, :-1]
        return incremental

    @property
    def latest_index(self) -> np.ndarray:
        return self.observed.sum(axis=1) - 1

    @property
    def latest(self) -> np.ndarray:
        return self.cumulative[np.arange(len(self.origins)), self.latest_index]


@dataclass(frozen=True)
class TriangleSet:
    settings: TriangleSettings
    reporting_currency: str
    cut_off: date
    origin_basis: str  # accident, report, first_valuation (proxy) or mixed
    proxy_claims: int
    claims_used: int
    triangles: tuple[Triangle, ...]
    not_converted: pl.DataFrame  # currency, claims, paid, incurred at the cut-off
    findings: tuple[Finding, ...]

    @property
    def groups(self) -> list[tuple[str, ...]]:
        return sorted({t.group for t in self.triangles})

    def get(self, measure: str, group: tuple[str, ...]) -> Triangle:
        return next(t for t in self.triangles if t.measure == measure and t.group == group)


def _month(column: str) -> pl.Expr:
    return pl.col(column).dt.year().cast(pl.Int64) * 12 + pl.col(column).dt.month() - 1


def _claim_origins(
    first: pl.DataFrame, claims: pl.DataFrame | None, settings: TriangleSettings, cut_off: date
) -> tuple[pl.DataFrame, list[Finding]]:
    """claim_id, origin month, proxy flag and group per claim; claims without a usable origin
    are left out and reported."""
    proxy = first.select(
        "claim_id",
        pl.col("first_month").alias("origin_month"),
        pl.lit(True).alias("proxy"),
        *[pl.lit(UNKNOWN).alias(f) for f in GROUP_FIELDS],
    )
    if claims is None:
        return proxy, []
    headers = first.join(claims, on="claim_id", how="inner")
    groups = [pl.col(f) for f in GROUP_FIELDS]
    if settings.origin_axis == OriginAxis.FIRST_VALUATION:
        with_header = headers.select(
            "claim_id",
            pl.col("first_month").alias("origin_month"),
            pl.lit(True).alias("proxy"),
            *groups,
        )
        findings: list[Finding] = []
    else:
        field = _ORIGIN_FIELD[settings.origin_axis]
        empty = headers.filter(pl.col(field).is_null())
        late = headers.filter(pl.col(field) > cut_off)
        findings = [
            f
            for f in (
                finding(
                    "claims",
                    "MT01",
                    "WARNING",
                    f"claims without {field} left out of the triangles",
                    empty,
                ),
                finding(
                    "claims",
                    "DV-CLM-07",
                    "WARNING",
                    f"claims with {field} after the cut-off left out of the triangles",
                    late,
                ),
            )
            if f is not None
        ]
        with_header = headers.filter(pl.col(field).is_not_null() & (pl.col(field) <= cut_off))
        with_header = with_header.select(
            "claim_id", _month(field).alias("origin_month"), pl.lit(False).alias("proxy"), *groups
        )
    without_header = proxy.join(headers.select("claim_id"), on="claim_id", how="anti")
    return pl.concat([with_header, without_header]).sort("claim_id"), findings


def _origin_basis(settings: TriangleSettings, proxy_claims: int, claims_used: int) -> str:
    if settings.origin_axis == OriginAxis.FIRST_VALUATION or proxy_claims == claims_used:
        return "first_valuation (proxy)"
    if proxy_claims:
        return f"mixed: {settings.origin_axis.value}, first_valuation proxy for some claims"
    return settings.origin_axis.value


def build_triangles(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    settings: TriangleSettings,
    rates: Mapping[str, float],
    reporting_currency: str,
) -> TriangleSet:
    """Paid and incurred triangles per group in the reporting currency.

    `rates` holds the constant development rate per original currency (CV01); amounts in a
    currency without a rate are not converted and are reported in `not_converted`.
    """
    cut_off = settings.cut_off or valuations["valuation_date"].max()
    if not isinstance(cut_off, date):
        raise TriangleError("claim_valuations has no usable rows")
    cut_off = month_end(month_index(cut_off))
    c = month_index(cut_off)
    l_o = settings.origin_period.months
    l_d = settings.development_period.months
    offset = settings.fiscal_year_start_month - 1

    rows = valuations.filter(pl.col("valuation_date") <= cut_off).with_columns(
        _month("valuation_date").alias("month")
    )
    first = rows.group_by("claim_id").agg(pl.col("month").min().alias("first_month"))
    origins, findings = _claim_origins(first, claims, settings, cut_off)
    origins = origins.with_columns(
        ((pl.col("origin_month") - offset) // l_o * l_o + offset).alias("origin_start")
    )
    if origins.height == 0:
        raise TriangleError("no claim has a usable origin, so no triangle is built (MT01)")

    earliest = int(origins["origin_start"].min())  # type: ignore[arg-type]
    first_point = c - (c - earliest) // l_d * l_d
    n_points = (c - first_point) // l_d + 1
    points = tuple(month_end(first_point + k * l_d) for k in range(n_points))
    starts = list(range(earliest, (c - offset) // l_o * l_o + offset + 1, l_o))
    labels = tuple(
        period_label(s, settings.origin_period, settings.fiscal_year_start_month) for s in starts
    )
    ages = tuple(first_point - earliest + 1 + j * l_d for j in range(n_points))
    first_bucket = {s: -((first_point - s) // l_d) for s in starts}

    rate = pl.col("currency").replace_strict(dict(rates), default=None, return_dtype=pl.Float64)
    data = (
        rows.join(origins, on="claim_id", how="inner")
        .with_columns(
            (-((first_point - pl.max_horizontal("month", "origin_start")) // l_d)).alias("bucket"),
            rate.alias("rate"),
            pl.col("paid_to_date").alias("paid"),
            (pl.col("paid_to_date") + pl.col("case_reserve")).alias("incurred"),
        )
        .sort("claim_id", "valuation_date", SOURCE_ROW)
    )

    keys = [*GROUP_FIELDS, "origin_start", "bucket"]
    reported = (
        data.unique(subset="claim_id", keep="first", maintain_order=True)
        .group_by(keys)
        .agg(pl.len().alias("value"))
    )
    increments: dict[str, pl.DataFrame] = {}
    for measure in MEASURES:
        increments[measure] = (
            data.filter(pl.col(measure).is_not_null())  # DV-CLV-02: row left out of the measure
            .unique(subset=["claim_id", "bucket"], keep="last", maintain_order=True)
            .with_columns((pl.col(measure) * pl.col("rate")).fill_null(0.0).alias("amount"))
            .with_columns(
                pl.col("amount").diff().over("claim_id").fill_null(pl.col("amount")).alias("delta")
            )
            .group_by(keys)
            .agg(pl.col("delta").sum().alias("value"))
        )

    def grid(frame: pl.DataFrame, group: tuple[str, ...]) -> np.ndarray:
        cells = np.zeros((len(starts), n_points))
        row_of = {s: i for i, s in enumerate(starts)}
        selected = frame.filter(
            pl.all_horizontal(pl.col(f) == v for f, v in zip(GROUP_FIELDS, group, strict=True))
        )
        for start, bucket, value in selected.select("origin_start", "bucket", "value").iter_rows():
            cells[row_of[start], bucket - first_bucket[start]] += value
        return np.cumsum(cells, axis=1)

    future = np.array(
        [[j > n_points - 1 - first_bucket[s] for j in range(n_points)] for s in starts]
    ).reshape(len(starts), n_points)
    calendar = np.array([[first_bucket[s] + j for j in range(n_points)] for s in starts]).reshape(
        len(starts), n_points
    )
    calendar[future] = -1

    group_values = sorted(origins.select(GROUP_FIELDS).unique().iter_rows())
    triangles: list[Triangle] = []
    for group in group_values:
        counts = grid(reported, group).astype(np.int64)
        counts[future] = -1
        for measure in MEASURES:
            cumulative = grid(increments[measure], group)
            cumulative[future] = np.nan
            triangles.append(
                Triangle(measure, group, labels, ages, cumulative, counts, calendar, points)
            )

    as_of = data.unique(subset="claim_id", keep="last", maintain_order=True)
    not_converted = (
        as_of.filter(pl.col("rate").is_null())
        .group_by("currency")
        .agg(
            pl.len().alias("claims"),
            pl.col("paid").sum().alias("paid"),
            pl.col("incurred").sum().alias("incurred"),
        )
        .sort("currency")
    )
    proxy_claims = int(origins["proxy"].sum())
    return TriangleSet(
        settings=settings,
        reporting_currency=reporting_currency,
        cut_off=cut_off,
        origin_basis=_origin_basis(settings, proxy_claims, origins.height),
        proxy_claims=proxy_claims,
        claims_used=origins.height,
        triangles=tuple(triangles),
        not_converted=not_converted,
        findings=tuple(findings),
    )
