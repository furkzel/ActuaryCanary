"""Helpers shared by the measure families: periods, lineage columns, result frames."""

from collections.abc import Iterable, Sequence
from datetime import date

import polars as pl

from actuarycanary.measures.model import REF, REFS_PREFIX, VALUE
from actuarycanary.structures.periods import (
    Period,
    month_end,
    month_index,
    period_label,
    period_start,
)

UNKNOWN = "UNKNOWN"
TOLERANCE = 1e-9


def month_number(column: str | pl.Expr) -> pl.Expr:
    expr = pl.col(column) if isinstance(column, str) else column
    return expr.dt.year().cast(pl.Int64) * 12 + expr.dt.month() - 1


def period_start_expr(column: str, period: Period, fiscal_start: int) -> pl.Expr:
    offset = fiscal_start - 1
    return (month_number(column) - offset) // period.months * period.months + offset


def add_period(
    frame: pl.DataFrame, column: str, name: str, period: Period, fiscal_start: int
) -> pl.DataFrame:
    """Add the CV04 label of the period that contains the date in `column` as `name`."""
    starts = frame.select(period_start_expr(column, period, fiscal_start).alias("s")).to_series()
    labels = {s: period_label(s, period, fiscal_start) for s in starts.drop_nulls().unique()}
    return frame.with_columns(
        starts.replace_strict(labels, default=None, return_dtype=pl.String).alias(name)
    )


def refs(concept: str, column: str = REF) -> pl.Expr:
    """Aggregation that keeps the source references of a concept (lineage)."""
    return pl.col(column).unique().sort().alias(REFS_PREFIX + concept)


def ratio_columns(numerator: str = "numerator", denominator: str = "denominator") -> list[pl.Expr]:
    """`value` as numerator / denominator, null when the denominator is not positive."""
    positive = pl.col(denominator) > 0
    return [
        pl.when(positive).then(pl.col(numerator) / pl.col(denominator)).otherwise(None).alias(VALUE)
    ]


def note_when(condition: pl.Expr, text: str) -> pl.Expr:
    """A `note` expression: `text` where `condition` holds, otherwise empty."""
    return pl.when(condition).then(pl.lit(text)).otherwise(pl.lit(""))


def ordered(columns: Iterable[str], keys: Sequence[str]) -> list[str]:
    """The breakdown columns first, in the order asked, then the rest."""
    rest = [c for c in columns if c not in keys]
    return [*[k for k in keys if k in columns], *rest]


def periods_between(
    first: date, last: date, period: Period, fiscal_start: int
) -> list[tuple[str, int, date]]:
    """(label, first month, last day) of every period from the one that contains `first` to the
    one that contains `last`."""
    start = period_start(month_index(first), period, fiscal_start)
    stop = period_start(month_index(last), period, fiscal_start)
    return [
        (period_label(s, period, fiscal_start), s, month_end(s + period.months - 1))
        for s in range(start, stop + 1, period.months)
    ]


def span_labels(first: object, last: object, period: Period, fiscal_start: int) -> list[str]:
    """Labels of the periods from the one that contains `first` to the one that contains `last`;
    empty when either is not a date (a column without dates)."""
    if not isinstance(first, date) or not isinstance(last, date):
        return []
    return [label for label, _, _ in periods_between(first, last, period, fiscal_start)]


def group_agg(frame: pl.DataFrame, keys: Sequence[str], aggs: Sequence[pl.Expr]) -> pl.DataFrame:
    """`group_by(keys).agg(aggs)`, also for no keys (one row over the whole frame)."""
    if keys:
        return frame.group_by(list(keys), maintain_order=True).agg(list(aggs))
    return (
        frame.with_columns(pl.lit(0).alias("_all"))
        .group_by("_all", maintain_order=True)
        .agg(list(aggs))
        .drop("_all")
    )


def keep_columns(frame: pl.DataFrame, keys: Sequence[str]) -> pl.DataFrame:
    """The frame with the breakdown columns first, then values, notes and lineage."""
    return frame.select(ordered(frame.columns, keys))


def ratio_frame(
    top: pl.DataFrame,
    bottom: pl.DataFrame,
    keys: Sequence[str],
    lineage: Sequence[str],
) -> pl.DataFrame:
    """Numerator frame over denominator frame (each with `value` and `refs_*` lists) on `keys`;
    a key only in one has 0 on the other side, the lineage of both is merged."""
    top = top.rename({VALUE: "numerator", **{c: c + "_top" for c in lineage if c in top.columns}})
    bottom = bottom.rename(
        {VALUE: "denominator", **{c: c + "_bottom" for c in lineage if c in bottom.columns}}
    )
    if keys:
        joined = top.join(bottom, on=list(keys), how="full", coalesce=True)
    else:
        joined = pl.concat([top, bottom], how="horizontal")
    merged = []
    for c in lineage:
        parts = [
            pl.col(col).fill_null(pl.lit([], dtype=pl.List(pl.UInt32)))
            for col in (c + "_top", c + "_bottom")
            if col in joined.columns
        ]
        if parts:
            merged.append(pl.concat_list(parts).list.unique().list.sort().alias(c))
    drop = [c for c in joined.columns if c.endswith(("_top", "_bottom"))]
    return (
        joined.with_columns(
            pl.col("numerator").fill_null(0.0),
            pl.col("denominator").fill_null(0.0),
            *merged,
        )
        .drop(drop)
        .with_columns(*ratio_columns())
    )
