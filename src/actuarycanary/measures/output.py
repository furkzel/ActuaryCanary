"""Measure results as flat tables for files: the values (unrounded, CV06) and their lineage.

`values_table` has one line per value and numeric column; `lineage_table` says which source
rows (file, sheet, row ranges) stand behind each value. Both name the measure, its spec version
and the row of the result they belong to.
"""

from collections.abc import Sequence

import polars as pl

from actuarycanary.measures.model import NOTE, REFS_PREFIX, MeasureInputs, MeasureResult

EXTRA_DIMENSIONS = ("count_type", "side", "measure", "method", "currency", "components")
VALUES_COLUMNS = (
    "measure",
    "version",
    "view",
    "basis",
    "row",
    "key",
    "column",
    "value",
    "note",
)
LINEAGE_COLUMNS = (
    "measure",
    "version",
    "view",
    "row",
    "concept",
    "file",
    "sheet",
    "rows",
    "count",
)


def view(result: MeasureResult) -> str:
    """The breakdowns the result was asked at, which tell several results of one measure apart."""
    return ",".join(result.request.breakdowns) or "all"


def dimensions(result: MeasureResult) -> list[str]:
    """The columns of the frame that name a group rather than hold a number."""
    if result.frame is None:
        return []
    frame = result.frame
    named = [c for c in result.request.breakdowns if c in frame.columns]
    return [*named, *[c for c in EXTRA_DIMENSIONS if c in frame.columns and c not in named]]


def _numeric(result: MeasureResult) -> list[str]:
    assert result.frame is not None
    skip = set(dimensions(result))
    return [
        c
        for c, dtype in result.frame.schema.items()
        if c not in skip and dtype.is_numeric() and not c.startswith(REFS_PREFIX)
    ]


def values_table(results: Sequence[MeasureResult]) -> pl.DataFrame:
    """Every numeric column of every result, one line each."""
    parts: list[pl.DataFrame] = []
    for result in results:
        if result.frame is None or result.frame.height == 0:
            continue
        dims = dimensions(result)
        key = (
            pl.concat_str(
                [pl.lit(f"{d}=") + pl.col(d).cast(pl.String).fill_null("") for d in dims],
                separator="; ",
            )
            if dims
            else pl.lit("")
        )
        indexed = result.frame.with_row_index("row").select(
            "row", key.alias("key"), NOTE, *_numeric(result)
        )
        long = indexed.unpivot(
            index=["row", "key", NOTE], variable_name="column", value_name="number"
        ).select(
            "row", "key", NOTE, "column", (pl.col("number").cast(pl.Float64) + 0.0).alias("value")
        )
        parts.append(
            long.with_columns(
                pl.lit(result.measure).alias("measure"),
                pl.lit(result.version).alias("version"),
                pl.lit(view(result)).alias("view"),
                pl.lit(result.request.basis.label()).alias("basis"),
            ).select(*VALUES_COLUMNS)
        )
    if not parts:
        return pl.DataFrame(schema={c: pl.String for c in VALUES_COLUMNS})
    return pl.concat(parts)


def _ranges(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """Sorted row numbers as "2-40;45" per key, and their count."""
    ordered = frame.sort([*keys, "source_row"])
    # a run starts where the key changes or the row number is not the previous one plus one,
    # and ends where the next row starts one; both are read off the sorted frame in one pass
    changed = pl.any_horizontal([pl.col(k).ne_missing(pl.col(k).shift(1)) for k in keys])
    consecutive = (pl.col("source_row") - pl.col("source_row").shift(1) == 1).fill_null(False)
    starts = ordered.select(
        pl.col("source_row").alias("low"), (changed | ~consecutive).alias("_start"), *keys
    )
    first = starts.filter(pl.col("_start")).drop("_start")
    last = pl.Series("high", ordered["source_row"]).filter(
        starts["_start"].shift(-1, fill_value=True)
    )
    runs = first.with_columns(
        last,
        pl.when(pl.col("low") == last)
        .then(pl.col("low").cast(pl.String))
        .otherwise(pl.concat_str(pl.col("low"), pl.lit("-"), last.cast(pl.String)))
        .alias("span"),
        (last - pl.col("low") + 1).alias("n"),
    )
    return runs.group_by(keys, maintain_order=True).agg(
        pl.col("span").str.join(";").alias("rows"), pl.col("n").sum().alias("count")
    )


def lineage_table(results: Sequence[MeasureResult], inputs: MeasureInputs) -> pl.DataFrame:
    """The source rows behind each value, by reference: file, sheet and spreadsheet row ranges."""
    parts: list[pl.DataFrame] = []
    for result in results:
        if result.frame is None or result.frame.height == 0:
            continue
        indexed = result.frame.with_row_index("row")
        for concept in result.concepts:
            column = REFS_PREFIX + concept
            if column not in indexed.columns or concept not in inputs.feeds:
                continue
            exploded = (
                indexed.select("row", pl.col(column).alias("_ref"))
                .explode("_ref")
                .drop_nulls("_ref")
            )
            if exploded.height == 0:
                continue
            source = inputs.source_index(concept).rename(
                {"_source_file": "file", "_source_sheet": "sheet", "_source_row": "source_row"}
            )
            joined = exploded.join(source, on="_ref", how="left")
            table = _ranges(joined, ["row", "file", "sheet"])
            parts.append(
                table.with_columns(
                    pl.lit(result.measure).alias("measure"),
                    pl.lit(result.version).alias("version"),
                    pl.lit(view(result)).alias("view"),
                    pl.lit(concept).alias("concept"),
                ).select(*LINEAGE_COLUMNS)
            )
    if not parts:
        return pl.DataFrame(schema={c: pl.String for c in LINEAGE_COLUMNS})
    return pl.concat(parts)
