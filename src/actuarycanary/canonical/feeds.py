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

from actuarycanary.canonical.amounts import INCREMENTAL, TO_DATE, accumulate
from actuarycanary.canonical.amounts import RULE as ACCUMULATED_RULE
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

    # DV-CLV-03: an empty or invalid currency takes the one valid currency the other rows of
    # its claim carry; without exactly one, it becomes UNKNOWN
    invalid = _invalid_currency()
    valid_currencies = (
        frame.filter(~invalid)
        .group_by("claim_id")
        .agg(pl.col("currency").unique().alias("_claim_currencies"))
        .filter(pl.col("_claim_currencies").list.len() == 1)
        .select("claim_id", pl.col("_claim_currencies").list.first().alias("_claim_currency"))
    )
    frame = frame.join(valid_currencies, on="claim_id", how="left", maintain_order="left")
    taken = invalid & pl.col("_claim_currency").is_not_null()
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-03",
            "WARNING",
            "empty or invalid currency taken from the other rows of the claim",
            frame.filter(taken),
        )
    )
    found.append(
        finding(
            "claim_valuations",
            "DV-CLV-03",
            "WARNING",
            f"empty or invalid currency becomes {UNKNOWN}",
            frame.filter(invalid & ~taken),
        )
    )
    frame = frame.with_columns(
        pl.when(taken)
        .then(pl.col("_claim_currency"))
        .when(invalid)
        .then(pl.lit(UNKNOWN))
        .otherwise(pl.col("currency"))
        .alias("currency")
    ).drop("_claim_currency")

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


def _invalid_currency(column: str = "currency") -> pl.Expr:
    return pl.col(column).is_null() | ~pl.col(column).str.contains(CURRENCY_CODE.pattern)


def _market_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    found: list[Finding | None] = []
    missing = pl.any_horizontal(pl.col(c).is_null() for c in ("series_id", "date", "value", "kind"))
    found.append(
        finding(
            "market",
            "DV-MKT-01",
            "BLOCKING",
            "rows without series, date, value or kind excluded",
            frame.filter(missing),
        )
    )
    frame = frame.filter(~missing)
    found.append(
        finding(
            "market",
            "DV-MKT-03",
            "BLOCKING",
            "rows with a value that is not strictly positive excluded",
            frame.filter(pl.col("value") <= 0),
        )
    )
    frame = frame.filter(pl.col("value") > 0)

    classes = next(f.classes for f in spec.fields if f.name == "kind")
    unmapped = ~pl.col("kind").is_in(classes)
    found.append(
        finding(
            "market",
            "DV-MKT-05",
            "WARNING",
            f"kind labels outside the classes become {UNMAPPED} and are excluded",
            frame.filter(unmapped),
        )
    )
    frame = frame.filter(~unmapped)

    fx_form = pl.col("series_id").str.contains(r"^[A-Z]{3}/[A-Z]{3}$") & (
        pl.col("series_id").str.slice(0, 3) != pl.col("series_id").str.slice(4, 3)
    )
    is_index = pl.col("kind") == "PRICE_INDEX"
    wrong_form = (is_index & fx_form) | (~is_index & ~fx_form)
    found.append(
        finding(
            "market",
            "DV-MKT-04",
            "WARNING",
            "series_id does not suit its kind (FX is BASE/QUOTE, a price index is not): excluded",
            frame.filter(wrong_form),
        )
    )
    frame = frame.filter(~wrong_form)

    # DV-MKT-02: of several values for one key (a date, or a month for the monthly kinds)
    # the later date, then the later source row is kept
    day = pl.col("date").dt.strftime("%Y-%m-%d")
    key = pl.when(pl.col("kind") == "FX_SPOT").then(day).otherwise(day.str.slice(0, 7))
    frame = frame.with_columns(key.alias("_key")).sort("date", SOURCE_ROW)
    last = frame.select(pl.struct("series_id", "kind", "_key").is_last_distinct()).to_series()
    found.append(
        finding(
            "market",
            "DV-MKT-02",
            "WARNING",
            "several values for one series, kind and date or month: the latest is kept",
            frame.filter(~last),
        )
    )
    return frame.filter(last).drop("_key").sort(SOURCE_ROW), found


# Canonical sign of each premium type (CV05); ENDORSEMENT has none
_PREMIUM_SIGN = {
    "WRITTEN": 1,
    "CANCELLATION": -1,
    "REFUND": -1,
    "COMMISSION": 1,
    "CEDED_PREMIUM": 1,
    "RI_COMMISSION": 1,
}


def _premiums_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    found: list[Finding | None] = []
    keyless = pl.col("transaction_id").is_null() | pl.col("policy_id").is_null()
    found.append(
        finding(
            "premiums",
            "DV-PRM-01",
            "BLOCKING",
            "rows without transaction_id or policy_id excluded",
            frame.filter(keyless),
        )
    )
    frame = frame.filter(~keyless).sort(SOURCE_ROW)

    value_columns = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    first = frame.select(pl.col("transaction_id").is_first_distinct()).to_series()
    identical = ~first & ~_first_distinct(frame, value_columns)
    found.append(
        finding(
            "premiums",
            "DV-PRM-02",
            "WARNING",
            "identical duplicate transactions kept once",
            frame.filter(identical),
        )
    )
    found.append(
        finding(
            "premiums",
            "DV-PRM-02",
            "WARNING",
            "conflicting rows for one transaction_id: the first row is kept",
            frame.filter(~first & ~identical),
        )
    )
    frame = frame.filter(first)

    incomplete = pl.any_horizontal(
        pl.col(c).is_null() for c in ("booking_date", "amount", "currency", "type")
    )
    found.append(
        finding(
            "premiums",
            "DV-PRM-03",
            "WARNING",
            "rows without booking_date, amount, currency or type excluded from premium measures",
            frame.filter(incomplete),
        )
    )
    frame = frame.filter(~incomplete)

    classes = next(f.classes for f in spec.fields if f.name == "type")
    unmapped = ~pl.col("type").is_in(classes)
    found.append(
        finding(
            "premiums",
            "DV-PRM-04",
            "WARNING",
            f"type labels outside the classes become {UNMAPPED} and are excluded from measures",
            frame.filter(unmapped),
        )
    )
    frame = frame.with_columns(
        pl.when(unmapped).then(pl.lit(UNMAPPED)).otherwise(pl.col("type")).alias("type")
    )

    invalid = _invalid_currency()
    found.append(
        finding(
            "premiums",
            "DV-PRM-05",
            "WARNING",
            f"invalid currency becomes {UNKNOWN}",
            frame.filter(invalid),
        )
    )
    frame = frame.with_columns(
        pl.when(invalid).then(pl.lit(UNKNOWN)).otherwise(pl.col("currency")).alias("currency")
    )

    # CV05 / DV-PRM-08: a type stored with the opposite sign convention is flipped as a whole
    flipped: list[str] = []
    for kind, sign in _PREMIUM_SIGN.items():
        amounts = frame.filter((pl.col("type") == kind) & (pl.col("amount") != 0))["amount"]
        if amounts.len() and (amounts * sign < 0).sum() * 2 > amounts.len():
            flipped.append(kind)
    if flipped:
        found.append(
            finding(
                "premiums",
                "DV-PRM-08",
                "INFO",
                f"types stored with the opposite sign convention flipped: {', '.join(flipped)}",
                frame.filter(pl.col("type").is_in(flipped)),
            )
        )
        frame = frame.with_columns(
            pl.when(pl.col("type").is_in(flipped))
            .then(-pl.col("amount"))
            .otherwise(pl.col("amount"))
            .alias("amount")
        )
    return frame, found


def _policies_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    found: list[Finding | None] = []
    keyless = pl.col("policy_id").is_null()
    found.append(
        finding(
            "policies",
            "DV-POL-01",
            "BLOCKING",
            "rows without policy_id excluded",
            frame.filter(keyless),
        )
    )
    frame = frame.filter(~keyless).sort(SOURCE_ROW)

    value_columns = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    first = frame.select(pl.col("policy_id").is_first_distinct()).to_series()
    identical = ~first & ~_first_distinct(frame, value_columns)
    found.append(
        finding(
            "policies",
            "DV-POL-02",
            "WARNING",
            "identical duplicate policies kept once",
            frame.filter(identical),
        )
    )
    found.append(
        finding(
            "policies",
            "DV-POL-02",
            "WARNING",
            "conflicting rows for one policy_id: the first row is kept",
            frame.filter(~first & ~identical),
        )
    )
    frame = frame.filter(first)

    found.append(
        finding(
            "policies",
            "DV-POL-03",
            "WARNING",
            "policies without start_date or end_date earn nothing",
            frame.filter(pl.col("start_date").is_null() | pl.col("end_date").is_null()),
        )
    )
    for name in ("segment", "line"):
        found.append(
            finding(
                "policies",
                "DV-POL-03",
                "WARNING",
                f"empty {name} reported as {UNKNOWN}",
                frame.filter(pl.col(name).is_null()),
            )
        )
    found.append(
        finding(
            "policies",
            "DV-POL-04",
            "WARNING",
            "start_date on or after end_date: premium earned in full on start_date, no exposure",
            frame.filter(pl.col("start_date") >= pl.col("end_date")),
        )
    )
    if "cancellation_date" in frame.columns:
        outside = (
            pl.col("cancellation_date").is_not_null()
            & pl.col("start_date").is_not_null()
            & pl.col("end_date").is_not_null()
            & (
                (pl.col("cancellation_date") < pl.col("start_date"))
                | (pl.col("cancellation_date") > pl.col("end_date"))
            )
        )
        found.append(
            finding(
                "policies",
                "DV-POL-05",
                "WARNING",
                "cancellation_date outside the cover period ignored for exposure",
                frame.filter(outside),
            )
        )
        frame = frame.with_columns(
            pl.when(outside)
            .then(None)
            .otherwise(pl.col("cancellation_date"))
            .alias("cancellation_date")
        )
    found.append(
        finding(
            "policies",
            "DV-POL-06",
            "WARNING",
            "currency is not a valid ISO 4217 code",
            frame.filter(_invalid_currency()),
        )
    )
    classes = next(f.classes for f in spec.fields if f.name == "segment")
    unmapped = pl.col("segment").is_not_null() & ~pl.col("segment").is_in(classes)
    found.append(
        finding(
            "policies",
            "DV-POL-07",
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
    if "exposure_units" in frame.columns:
        negative = pl.col("exposure_units") < 0
        found.append(
            finding(
                "policies",
                "DV-POL-08",
                "WARNING",
                "negative exposure_units replaced by zero for exposure",
                frame.filter(negative),
            )
        )
        frame = frame.with_columns(
            pl.when(negative).then(0.0).otherwise(pl.col("exposure_units")).alias("exposure_units")
        )
    return frame, found


RATE_MIN, RATE_MAX = -0.05, 2.0  # DV-IRT-04
MONTHS_PER_YEAR = 12


def _interest_rate_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    """DV-IRT-01 to -07 and -10: the rows that cannot be a point of a curve are excluded."""
    found: list[Finding | None] = []
    concept = "interest_rates"
    required = ("curve_id", "date", "tenor_months", "rate", "rate_type", "currency")
    missing = pl.any_horizontal(pl.col(c).is_null() for c in required)
    found.append(
        finding(
            concept,
            "DV-IRT-01",
            "BLOCKING",
            "rows without curve_id, date, tenor_months, rate, rate_type or currency excluded",
            frame.filter(missing),
        )
    )
    frame = frame.filter(~missing)

    if "compounding" in frame.columns:
        frame = frame.with_columns(pl.col("compounding").fill_null("ANNUAL"))
    mapped = pl.col("rate_type").is_in(
        next(f.classes for f in spec.fields if f.name == "rate_type")
    )
    if "compounding" in frame.columns:
        classes = next(f.classes for f in spec.fields if f.name == "compounding")
        mapped = mapped & pl.col("compounding").is_in(classes)
    found.append(
        finding(
            concept,
            "DV-IRT-02",
            "WARNING",
            f"rate_type or compounding labels outside the classes become {UNMAPPED} and the "
            "rows are excluded",
            frame.filter(~mapped),
        )
    )
    frame = frame.filter(mapped)

    bad_tenor = ~(
        (pl.col("tenor_months") > 0) & (pl.col("tenor_months") == pl.col("tenor_months").round(0))
    )
    found.append(
        finding(
            concept,
            "DV-IRT-03",
            "WARNING",
            "tenor_months is not a positive whole number: rows excluded",
            frame.filter(bad_tenor),
        )
    )
    frame = frame.filter(~bad_tenor).with_columns(pl.col("tenor_months").cast(pl.Int64))

    bad_rate = ~pl.col("rate").is_between(RATE_MIN, RATE_MAX)
    found.append(
        finding(
            concept,
            "DV-IRT-04",
            "WARNING",
            f"rate outside {RATE_MIN} to {RATE_MAX} (a year): rows excluded; a rate given in per "
            "cent (25 for 0.25) is the usual cause",
            frame.filter(bad_rate),
        )
    )
    frame = frame.filter(~bad_rate)

    invalid = _invalid_currency()
    found.append(
        finding(
            concept,
            "DV-IRT-05",
            "WARNING",
            "currency is not a valid ISO 4217 code: rows excluded",
            frame.filter(invalid),
        )
    )
    frame = frame.filter(~invalid)
    # the currency of a curve is the one of most of its rows, then of the earliest row
    home = (
        frame.group_by("curve_id", "currency")
        .agg(pl.len().alias("n"), pl.col(SOURCE_ROW).min().alias("first"))
        .sort("curve_id", "n", "first", descending=[False, True, False])
        .unique("curve_id", keep="first", maintain_order=True)
        .select("curve_id", pl.col("currency").alias("home"))
    )
    frame = frame.join(home, on="curve_id", how="left")
    other = pl.col("currency") != pl.col("home")
    found.append(
        finding(
            concept,
            "DV-IRT-05",
            "WARNING",
            "rows of a curve in a second currency excluded",
            frame.filter(other),
        )
    )
    frame = frame.filter(~other).drop("home")

    key = ["curve_id", "date", "tenor_months"]
    frame = frame.sort(SOURCE_ROW)
    last = frame.select(pl.struct(key).is_last_distinct()).to_series()
    found.append(
        finding(
            concept,
            "DV-IRT-06",
            "WARNING",
            "several rates for one curve, date and tenor: the later source row is kept",
            frame.filter(~last),
        )
    )
    frame = frame.filter(last)

    mixed = pl.col("rate_type").n_unique().over("curve_id", "date") > 1
    if "compounding" in frame.columns:
        mixed = mixed | (pl.col("compounding").n_unique().over("curve_id", "date") > 1)
    found.append(
        finding(
            concept,
            "DV-IRT-07",
            "WARNING",
            "a curve on one date with more than one rate_type or compounding: that curve on "
            "that date excluded",
            frame.filter(mixed),
        )
    )
    frame = frame.filter(~mixed)

    whole_year = pl.col("rate_type").is_in(["PAR", "FORWARD"]) & (
        pl.col("tenor_months") % MONTHS_PER_YEAR != 0
    )
    found.append(
        finding(
            concept,
            "DV-IRT-10",
            "WARNING",
            "PAR and FORWARD rows need a tenor of whole years: rows excluded",
            frame.filter(whole_year),
        )
    )
    return frame.filter(~whole_year), found


# --- the feeds built by F1bc: movements with an id (recoveries, reinsurance transactions),
# treaty terms and the trial balance (records 0381, 0384) ---------------------------------


def _unmapped_labels(
    frame: pl.DataFrame, spec: DataConceptSpec, fields: tuple[str, ...], rule: str, what: str
) -> tuple[pl.DataFrame, Finding | None]:
    """Labels of the classified `fields` outside their classes become UNMAPPED and are listed."""
    classes = {f.name: f.classes for f in spec.fields if f.name in fields and f.classes}
    used = [f for f in fields if f in classes and f in frame.columns]
    if not used:
        return frame, None
    bad = {f: pl.col(f).is_not_null() & ~pl.col(f).is_in(classes[f]) for f in used}
    found = finding(
        spec.id,
        rule,
        "WARNING",
        f"{' and '.join(used)} labels outside the classes become {UNMAPPED}{what}",
        frame.filter(pl.any_horizontal(*bad.values())),
    )
    frame = frame.with_columns(
        pl.when(bad[f]).then(pl.lit(UNMAPPED)).otherwise(pl.col(f)).alias(f) for f in used
    )
    return frame, found


def _one_per_key(
    frame: pl.DataFrame, concept: str, rule: str, keys: list[str], conflicting: str
) -> tuple[pl.DataFrame, list[Finding | None]]:
    """Identical duplicates of a key are kept once. Conflicting rows of one key: with
    `conflicting` "later" the later source row is kept, with "none" all of them are excluded."""
    frame = frame.sort(SOURCE_ROW)
    value_columns = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    identical = ~_first_distinct(frame, value_columns)
    found = [
        finding(
            concept,
            rule,
            "WARNING",
            f"identical duplicates of {', '.join(keys)} kept once",
            frame.filter(identical),
        )
    ]
    frame = frame.filter(~identical)
    key = pl.struct(keys)
    if conflicting == "later":
        last = frame.select(key.is_last_distinct()).to_series()
        found.append(
            finding(
                concept,
                rule,
                "WARNING",
                f"conflicting rows for one {', '.join(keys)}: the later row is kept",
                frame.filter(~last),
            )
        )
        return frame.filter(last), found
    repeated = frame.select(key.is_duplicated()).to_series()
    found.append(
        finding(
            concept,
            rule,
            "WARNING",
            f"conflicting rows for one {', '.join(keys)}: all of them excluded",
            frame.filter(repeated),
        )
    )
    return frame.filter(~repeated), found


def _movement_rules(
    frame: pl.DataFrame,
    spec: DataConceptSpec,
    prefix: str,
    owner: str,
    classified: tuple[str, ...],
    unmapped_note: str,
) -> tuple[pl.DataFrame, list[Finding | None]]:
    """Rules 01 to 04 of a movement feed with a transaction_id (recoveries, reinsurance
    transactions): presence, classes, currency, one row per transaction."""
    concept = spec.id
    required = ("transaction_id", owner, "booking_date", "amount", "type")
    missing = pl.any_horizontal(pl.col(c).is_null() for c in required)
    found: list[Finding | None] = [
        finding(
            concept,
            f"{prefix}-01",
            "BLOCKING",
            f"rows without {', '.join(required[:-1])} or {required[-1]} excluded",
            frame.filter(missing),
        )
    ]
    frame = frame.filter(~missing)
    frame, duplicates = _one_per_key(frame, concept, f"{prefix}-04", ["transaction_id"], "later")
    found += duplicates
    frame, unmapped = _unmapped_labels(frame, spec, classified, f"{prefix}-02", unmapped_note)
    found.append(unmapped)
    invalid = _invalid_currency()
    found.append(
        finding(
            concept,
            f"{prefix}-03",
            "WARNING",
            f"empty or invalid currency becomes {UNKNOWN}: kept in original-currency views, "
            "excluded from converted views",
            frame.filter(invalid),
        )
    )
    frame = frame.with_columns(
        pl.when(invalid).then(pl.lit(UNKNOWN)).otherwise(pl.col("currency")).alias("currency")
    )
    return frame.sort(SOURCE_ROW), found


def _recoveries_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    return _movement_rules(
        frame,
        spec,
        "DV-RCV",
        "claim_id",
        ("type", "counterparty_type"),
        "; such a type counts in total recoveries and in no measure by type",
    )


def _reinsurance_transactions_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    return _movement_rules(
        frame,
        spec,
        "DV-RTR",
        "treaty_id",
        ("type", "segment"),
        "; such a type is excluded from ceded measures",
    )


def _reinsurance_treaties_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    """Rows that cannot be told apart or placed in time are excluded (DV-RTY-01, -03, -08); the
    terms of a row (DV-RTY-04 to -07) are checked by the quality report and the row is kept, so
    that a movement can still be matched to its treaty (record 0384)."""
    concept = "reinsurance_treaties"
    required = ("treaty_id", "treaty_type", "inception_date", "expiry_date", "currency")
    missing = pl.any_horizontal(pl.col(c).is_null() for c in required)
    found: list[Finding | None] = [
        finding(
            concept,
            "DV-RTY-01",
            "BLOCKING",
            "rows without treaty_id, treaty_type, inception_date, expiry_date or currency excluded",
            frame.filter(missing),
        )
    ]
    frame = frame.filter(~missing)
    backwards = pl.col("expiry_date") <= pl.col("inception_date")
    found.append(
        finding(
            concept,
            "DV-RTY-03",
            "BLOCKING",
            "rows whose expiry_date is not after inception_date excluded",
            frame.filter(backwards),
        )
    )
    frame = frame.filter(~backwards)
    frame, unmapped = _unmapped_labels(
        frame,
        spec,
        ("treaty_type", "attachment_basis", "loss_basis", "segment"),
        "DV-RTY-02",
        f"; a row with an {UNMAPPED} treaty_type is excluded from allocation and what-if",
    )
    found.append(unmapped)
    keys = [k for k in ("treaty_id", "inception_date", "line") if k in frame.columns]
    frame, duplicates = _one_per_key(frame, concept, "DV-RTY-08", keys, "none")
    return frame.sort(SOURCE_ROW), [*found, *duplicates]


def _ledger_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    concept = "ledger"
    required = ("entity", "account", "period", "closing_balance")
    missing = pl.any_horizontal(pl.col(c).is_null() for c in required)
    found: list[Finding | None] = [
        finding(
            concept,
            "DV-LDG-01",
            "BLOCKING",
            "rows without entity, account, period or closing_balance excluded",
            frame.filter(missing),
        )
    ]
    frame = frame.filter(~missing)
    month_end = pl.col("period").dt.month_end()
    found.append(
        finding(
            concept,
            "DV-LDG-02",
            "INFO",
            "period is not a month end: the row is assigned to the month end of its month",
            frame.filter(pl.col("period") != month_end),
        )
    )
    frame = frame.with_columns(month_end.alias("period"))
    frame, unmapped = _unmapped_labels(
        frame,
        spec,
        ("account_class", "segment"),
        "DV-LDG-04",
        "; the mapping profile may still map the account",
    )
    found.append(unmapped)
    keys = [k for k in ("entity", "account", "period", "currency") if k in frame.columns]
    frame, duplicates = _one_per_key(frame, concept, "DV-LDG-05", keys, "none")
    return frame.sort(SOURCE_ROW), [*found, *duplicates]


_RULES: dict[
    str, Callable[[pl.DataFrame, DataConceptSpec], tuple[pl.DataFrame, list[Finding | None]]]
] = {
    "claim_valuations": _claim_valuation_rules,
    "claims": _claims_rules,
    "market": _market_rules,
    "premiums": _premiums_rules,
    "policies": _policies_rules,
    "interest_rates": _interest_rate_rules,
    "recoveries": _recoveries_rules,
    "reinsurance_transactions": _reinsurance_transactions_rules,
    "reinsurance_treaties": _reinsurance_treaties_rules,
    "ledger": _ledger_rules,
}


def canonicalise(table: RawTable, spec: DataConceptSpec, amounts: str = TO_DATE) -> CanonicalFeed:
    """Typed canonical feed of `spec.id` from a raw table whose columns use canonical names.
    `amounts` says whether claim valuations hold amounts cumulative to date or per period."""
    frame, findings = _typed(table.frame, spec)
    rules = _RULES.get(spec.id)
    if rules is not None:
        frame, found = rules(frame, spec)
        findings += [f for f in found if f is not None]
    if spec.id == "claim_valuations" and amounts == INCREMENTAL:
        # after the duplicates are gone, so that a repeated row is not added twice
        frame = accumulate(frame)
        added = finding(
            spec.id,
            ACCUMULATED_RULE,
            "INFO",
            "amounts given per period were added up per claim into amounts to date",
            frame,
        )
        if added:
            findings.append(added)
    fields = tuple(f.name for f in spec.fields if f.name in frame.columns)
    return CanonicalFeed(spec.id, spec.version, frame, fields, tuple(findings))
