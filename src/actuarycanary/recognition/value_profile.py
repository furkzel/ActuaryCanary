"""Value profile of a column (blueprint 6.3 layer 4): type, format, range and cardinality.

The profile confirms or rejects a name match and recognises personal data from values. It
keeps shares and counts only, never the values themselves, so it can be shown and stored.
"""

from dataclasses import dataclass
from typing import Any

import polars as pl

from actuarycanary.canonical.dates import parse_dates
from actuarycanary.canonical.feeds import as_text

SAMPLE = 5_000  # first non-empty values profiled per column

NUMBER = r"^[+-]?[\d.,]*\d([eE][+-]?\d+)?$"
DATE_LIKE = r"^\d{4}-\d{1,2}-\d{1,2}|^\d{1,2}[./-]\d{1,2}[./-]\d{4}"
CURRENCY = r"^[A-Z]{3}$"
NATIONAL_ID = r"^[1-9]\d{10}$"  # Turkish identity number: 11 digits, the first not zero
PHONE = r"^(\+?90|0)?[2-5]\d{9}$|^\+\d{10,14}$"  # after spaces, dashes, dots, brackets go
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
IBAN = r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$"
PERSON_NAME = r"^\p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+){1,3}$|^\p{Lu}{2,}( \p{Lu}{2,}){1,3}$"


@dataclass(frozen=True)
class ValueProfile:
    kind: str  # number, date, text, other or empty: the type the reader gave the column
    non_null: int
    distinct: int  # among the profiled values
    number_share: float
    date_share: float
    date_formats: tuple[str, ...]
    date_note: str
    currency_share: float
    national_id_share: float
    phone_share: float
    email_share: float
    iban_share: float
    person_name_share: float
    minimum: float | None
    maximum: float | None

    @property
    def distinct_share(self) -> float:
        profiled = min(self.non_null, SAMPLE)
        return self.distinct / profiled if profiled else 0.0

    def describe(self) -> str:
        """Short evidence text: type, fill, cardinality and range."""
        if self.kind == "empty":
            return "no values"
        parts = [f"{self.kind}", f"{self.non_null} values", f"{self.distinct} distinct"]
        if self.kind == "number" and self.minimum is not None:
            parts.append(f"range {self.minimum:,.6g} to {self.maximum:,.6g}")
        if self.kind == "text" and self.date_share > 0:
            parts.append(f"{self.date_share:.0%} dates ({', '.join(self.date_formats)})")
        if self.date_note:
            parts.append(self.date_note)
        return ", ".join(parts)


def _kind(series: pl.Series) -> str:
    if series.dtype == pl.Null or series.null_count() == series.len():
        return "empty"
    if series.dtype.is_numeric():
        return "number"
    if series.dtype in (pl.Date, pl.Datetime):
        return "date"
    if series.dtype == pl.String:
        return "text"
    return "other"


def _mean(flags: pl.Series) -> float:
    value = flags.cast(pl.Float64).mean()
    return float(value) if isinstance(value, int | float) else 0.0


def _shares(text: pl.Series) -> dict[str, float]:
    """Share of the values that fit each pattern, computed in one pass."""
    t = pl.col("text")
    compact = t.str.replace_all(r"[\s\-.()/]", "")
    patterns = {
        "number": t.str.contains(NUMBER),
        "date_like": t.str.contains(DATE_LIKE),
        "currency": t.str.contains(CURRENCY),
        "national_id": t.str.replace_all(r"\s", "").str.contains(NATIONAL_ID),
        "phone": compact.str.contains(PHONE),
        "email": t.str.contains(EMAIL),
        "iban": compact.str.to_uppercase().str.contains(IBAN),
        "person_name": t.str.contains(PERSON_NAME),
    }
    if text.len() == 0:
        return dict.fromkeys(patterns, 0.0)
    row = text.to_frame("text").select(
        e.cast(pl.Float64).mean().alias(k) for k, e in patterns.items()
    )
    return {k: float(v or 0.0) for k, v in row.row(0, named=True).items()}


def profile_values(series: pl.Series) -> ValueProfile:
    kind = _kind(series)
    values = series.drop_nulls().head(SAMPLE)
    text = as_text(values).str.strip_chars()
    text = text.filter(text != "")
    shares = _shares(text)
    minimum: Any = values.min() if kind == "number" else None
    maximum: Any = values.max() if kind == "number" else None
    if kind == "date":
        date_share, formats, note = 1.0, (), ""
    elif kind == "text" and shares["date_like"] > 0:
        parsed = parse_dates(text)
        date_share = _mean(parsed.values.is_not_null())
        formats, note = parsed.formats, parsed.note
    else:
        date_share, formats, note = 0.0, (), ""
    return ValueProfile(
        kind=kind,
        non_null=series.len() - series.null_count(),
        distinct=text.n_unique() if text.len() else 0,
        number_share=1.0 if kind == "number" else shares["number"],
        date_share=date_share,
        date_formats=formats,
        date_note=note,
        currency_share=shares["currency"],
        national_id_share=shares["national_id"],
        phone_share=shares["phone"],
        email_share=shares["email"],
        iban_share=shares["iban"],
        person_name_share=shares["person_name"],
        minimum=float(minimum) if isinstance(minimum, int | float) else None,
        maximum=float(maximum) if isinstance(maximum, int | float) else None,
    )
