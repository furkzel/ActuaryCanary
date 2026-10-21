"""Turns a raw table with canonical column names into a typed canonical feed.

Columns are matched by their exact canonical names here; recognition of other names is a
separate step that renames columns before this one. Each data concept specification
(spec/data) gives the fields and types; the row rules that change which rows or values
enter the analyses are applied here and reported as findings, never silently.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from actuarycanary.canonical.dates import parse_dates
from actuarycanary.io.excel import SOURCE_COLUMNS, SOURCE_ROW, RawTable
from actuarycanary.spec.models import DataConceptSpec

UNKNOWN = "UNKNOWN"
UNMAPPED = "UNMAPPED"
CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")  # shape of an ISO 4217 code
_ROWS_LISTED = 20  # source rows kept per finding; the count is always complete

_TYPES: dict[str, pl.DataType] = {"text": pl.String(), "date": pl.Date(), "number": pl.Float64()}


class CanonicalError(Exception):
    """The table cannot become the feed, for example because a required column is missing."""


@dataclass(frozen=True)
class Finding:
    """One rule that touched rows: what happened, how often, and the first source rows."""

    concept: str
    rule: str
    severity: str
    count: int
    message: str
    rows: tuple[int, ...] = ()


@dataclass(frozen=True)
class CanonicalFeed:
    concept: str
    spec_version: str
    frame: pl.DataFrame  # spec fields present in the source, plus the source columns
    fields: tuple[str, ...]
    findings: tuple[Finding, ...]


def finding(
    concept: str, rule: str, severity: str, message: str, rows: pl.DataFrame
) -> Finding | None:
    """A finding over `rows` (which carry the source row column), or None when there are none."""
    if rows.height == 0:
        return None
    listed = tuple(rows[SOURCE_ROW].head(_ROWS_LISTED).to_list())
    return Finding(concept, rule, severity, rows.height, message, listed)


def _first_distinct(frame: pl.DataFrame, columns: list[str]) -> pl.Series:
    return frame.select(pl.struct(columns).is_first_distinct()).to_series()


def as_text(source: pl.Series) -> pl.Series:
    """Text of each cell; whole numbers from number cells lose the ".0" (codes stay codes)."""
    if source.dtype.is_float():
        whole = source.is_null() | (source == source.round(0))
        if whole.all():
            return source.cast(pl.Int64, strict=False).cast(pl.String)
    return source.cast(pl.String)


def _typed(frame: pl.DataFrame, spec: DataConceptSpec) -> tuple[pl.DataFrame, list[Finding]]:
    """Keep the spec fields present, cast them to their spec types and report failed casts."""
    present = [f for f in spec.fields if f.name in frame.columns]
    missing = [f.name for f in spec.fields if f.required and f.name not in frame.columns]
    if missing:
        raise CanonicalError(f"{spec.file_name}: required columns missing: {', '.join(missing)}")
    findings: list[Finding] = []
    columns: list[pl.Expr | pl.Series] = []
    for field in present:
        source = frame[field.name]
        target = _TYPES[field.type]
        if field.type == "text":
            text = as_text(source).str.strip_chars()
            typed = pl.when(text == "").then(None).otherwise(text)
            columns.append(typed.alias(field.name))
            continue
        if source.dtype == target:
            columns.append(pl.col(field.name))
            continue
        cast = (
            parse_dates(source).values
            if field.type == "date"
            else source.cast(target, strict=False)
        )
        failed = frame.filter(source.is_not_null() & cast.is_null())
        found = finding(
            spec.id,
            "CV07",
            "WARNING",
            f"{field.name}: values that are not a {field.type} read as empty",
            failed,
        )
        if found:
            findings.append(found)
        columns.append(cast.alias(field.name))
    typed_frame = frame.select(*columns, *SOURCE_COLUMNS)
    return typed_frame, findings


def _claim_valuation_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    found: list[Finding | None] = []

    keyless = pl.col("claim_id").is_null() | pl.col("valuation_date").is_null()
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-01",
            "BLOCKING",
            "rows without claim_id or valuation_date excluded",
            frame.filter(keyless),
        )
    )
    frame = frame.filter(~keyless)

    month_end = pl.col("valuation_date").dt.month_end()
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-05",
            "INFO",
            "valuation_date moved to the month end",
            frame.filter(pl.col("valuation_date") != month_end),
        )
    )
    frame = frame.with_columns(
        pl.col("valuation_date").alias("_valuation_date_given"), month_end.alias("valuation_date")
    )

    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-02",
            "WARNING",
            "rows with an empty paid_to_date or case_reserve",
            frame.filter(pl.col("paid_to_date").is_null() | pl.col("case_reserve").is_null()),
        )
    )

    classes = next(f.classes for f in spec.fields if f.name == "status")
    unmapped = pl.col("status").is_null() | ~pl.col("status").is_in(classes)
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-04",
            "WARNING",
            f"status labels outside the classes become {UNMAPPED}",
            frame.filter(unmapped),
        )
    )
    frame = frame.with_columns(
        pl.when(unmapped).then(pl.lit(UNMAPPED)).otherwise(pl.col("status")).alias("status")
    )

    invalid = pl.col("currency").is_null() | ~pl.col("currency").str.contains(CURRENCY_CODE.pattern)
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-03",
            "WARNING",
            f"empty or invalid currency becomes {UNKNOWN}",
            frame.filter(invalid),
        )
    )
    frame = frame.with_columns(
        pl.when(invalid).then(pl.lit(UNKNOWN)).otherwise(pl.col("currency")).alias("currency")
    )

    # DV-CLV-06: identical duplicates kept once; conflicting ones keep the later given date,
    # then the later source row
    value_columns = [c for c in frame.columns if c not in (*SOURCE_COLUMNS, "valuation_date")]
    frame = frame.sort(SOURCE_ROW)
    identical = ~_first_distinct(frame, value_columns)
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-06",
            "WARNING",
            "identical duplicate rows kept once",
            frame.filter(identical),
        )
    )
    frame = frame.filter(~identical)
    frame = frame.sort(["claim_id", "valuation_date", "_valuation_date_given", SOURCE_ROW])
    later = frame.select(
        pl.struct("claim_id", "valuation_date").is_last_distinct().alias("keep")
    ).to_series()
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-06",
            "WARNING",
            "conflicting rows for one claim and month: the later row is kept",
            frame.filter(~later),
        )
    )
    frame = frame.filter(later).drop("_valuation_date_given").sort(SOURCE_ROW)
    return frame, found


def _claims_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    found: list[Finding | None] = []
    keyless = pl.col("claim_id").is_null()
    found.append(
        finding(
            "claims",
            "DV-CLM-01",
            "BLOCKING",
            "rows without claim_id excluded",
            frame.filter(keyless),
        )
    )
    frame = frame.filter(~keyless).sort(SOURCE_ROW)

    value_columns = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    first = frame.select(pl.col("claim_id").is_first_distinct()).to_series()
    identical = ~first & ~_first_distinct(frame, value_columns)
    found.append(
        finding(
            "claims",
            "DV-CLM-02",
            "WARNING",
            "identical duplicate claims kept once",
            frame.filter(identical),
        )
    )
    found.append(
        finding(
            "claims",
            "DV-CLM-02",
            "WARNING",
            "conflicting rows for one claim_id: the first row is kept",
            frame.filter(~first & ~identical),
        )
    )
    frame = frame.filter(first)

    for name in ("segment", "line"):
        found.append(
            finding(
                "claims",
                "DV-CLM-03",
                "WARNING",
                f"empty {name} reported as {UNKNOWN}",
                frame.filter(pl.col(name).is_null()),
            )
        )
    for name in ("occurrence_date", "report_date"):
        found.append(
            finding(
                "claims",
                "DV-CLM-03",
                "WARNING",
                f"empty {name}",
                frame.filter(pl.col(name).is_null()),
            )
        )
    classes = next(f.classes for f in spec.fields if f.name == "segment")
    unmapped = pl.col("segment").is_not_null() & ~pl.col("segment").is_in(classes)
    found.append(
        finding(
            "claims",
            "DV-CLM-06",
            "WARNING",
            f"segment labels outside the classes become {UNMAPPED}",
            frame.filter(unmapped),
        )
    )
    frame = frame.with_columns(
        pl.when(unmapped)
        .then(pl.lit(UNMAPPED))
        .otherwise(pl.col("segment").fill_null(UNKNOWN))
        .alias("segment"),
        pl.col("line").fill_null(UNKNOWN),
    )
    return frame, found


_RULES: dict[
    str, Callable[[pl.DataFrame, DataConceptSpec], tuple[pl.DataFrame, list[Finding | None]]]
] = {
    "claim_valuations": _claim_valuation_rules,
    "claims": _claims_rules,
}


def canonicalise(table: RawTable, spec: DataConceptSpec) -> CanonicalFeed:
    """Typed canonical feed of `spec.id` from a raw table whose columns use canonical names."""
    frame, findings = _typed(table.frame, spec)
    rules = _RULES.get(spec.id)
    if rules is not None:
        frame, found = rules(frame, spec)
        findings += [f for f in found if f is not None]
    fields = tuple(f.name for f in spec.fields if f.name in frame.columns)
    return CanonicalFeed(spec.id, spec.version, frame, fields, tuple(findings))
