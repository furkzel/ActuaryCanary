"""Column mapping for one concept, in deterministic layers (blueprint 6.3).

1. Normalise the header (``normalise_label``: Turkish-aware folding, accents, punctuation
   and spaces removed).
2. Dictionary: the token is the field's canonical name or one of its aliases (AL01).
3. Fuzzy: the token is close to an alias (rapidfuzz ratio at or above ``FUZZY_THRESHOLD``).
4. Value profile: type, format, range and cardinality confirm or reject each name candidate;
   a column of three-letter codes is proposed as the currency when no header names it.

Personal-data columns are recognised first and never mapped. Each field takes at most one
column and each column at most one field; candidates are assigned by confidence. Every
mapping carries its layer, confidence and evidence.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

import polars as pl
from rapidfuzz import fuzz, process

from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.personal import personal_kind
from actuarycanary.recognition.value_profile import ValueProfile, profile_values
from actuarycanary.spec.labels import normalise_label
from actuarycanary.spec.models import DataField

FUZZY_THRESHOLD = 85.0  # rapidfuzz ratio, 0-100
MIN_FUZZY_LENGTH = 4  # shorter tokens are matched exactly or not at all
CONFIRM_SHARE = 0.9  # share of values of the field's type that confirms a candidate
REJECT_SHARE = 0.5  # below this share the candidate is rejected
CLASS_SHARE = 0.5  # share of distinct labels recognised that confirms a classified field
UNCONFIRMED = 0.9  # confidence factor when the values neither confirm nor reject
VALUES_ONLY = 0.6  # confidence of a field proposed by the value profile alone
UNNAMED = "__UNNAMED__"  # prefix the reader gives columns with an empty header cell


class Layer(StrEnum):
    CANONICAL = "canonical"  # the header is the field's canonical name
    DICTIONARY = "dictionary"  # the header is an alias (AL01)
    FUZZY = "fuzzy"  # the header is close to an alias
    VALUES = "values"  # proposed by the value profile alone
    SAVED = "saved"  # taken from a saved mapping profile
    USER = "user"  # set by the user
    PERSONAL = "personal"  # personal data, dropped
    NONE = "none"  # not mapped


class Check(StrEnum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ColumnMapping:
    source: str  # header as written
    field: str | None
    layer: Layer
    confidence: float
    evidence: str
    personal: str | None = None  # personal-data kind; the column is dropped

    @property
    def used(self) -> bool:
        return self.field is not None and self.personal is None


@dataclass(frozen=True)
class _Candidate:
    column: int
    field: str
    layer: Layer
    confidence: float
    evidence: str


_LAYER_RANK = {Layer.CANONICAL: 0, Layer.DICTIONARY: 1, Layer.FUZZY: 2, Layer.VALUES: 3}


def class_share(series: pl.Series, lookup: dict[str, str]) -> float:
    """Share of the distinct labels of `series` that the value aliases recognise."""
    labels = series.drop_nulls().cast(pl.String).unique().head(500).to_list()
    labels = [label for label in labels if label.strip()]
    if not labels:
        return 0.0
    return sum(normalise_label(label) in lookup for label in labels) / len(labels)


def value_check(
    field: DataField, profile: ValueProfile, series: pl.Series, lookup: dict[str, str] | None
) -> tuple[Check, str]:
    """Does the column's content fit the field's type (and classes, and currency codes)?"""
    if profile.kind == "empty":
        return Check.UNCONFIRMED, "no values to check"
    if field.type == "date":
        share, what = profile.date_share, "dates"
    elif field.type == "number":
        share, what = profile.number_share, "numbers"
    elif field.name == "currency":
        share, what = profile.currency_share, "three-letter codes"
    elif lookup is not None:
        if profile.kind in ("number", "date"):
            return Check.REJECTED, f"values are {profile.kind}s, not class labels"
        share = class_share(series, lookup)
        if share >= CLASS_SHARE:
            return Check.CONFIRMED, f"{share:.0%} of distinct labels recognised (AL02)"
        return Check.UNCONFIRMED, f"only {share:.0%} of distinct labels recognised (AL02)"
    else:
        return Check.CONFIRMED, f"text, {profile.distinct} distinct"
    if share >= CONFIRM_SHARE:
        return Check.CONFIRMED, f"{share:.0%} {what}"
    if share < REJECT_SHARE:
        return Check.REJECTED, f"only {share:.0%} {what}"
    return Check.UNCONFIRMED, f"{share:.0%} {what}"


def _name_candidates(
    column: int, header: str, token: str, concept: str, dictionary: Dictionary
) -> list[_Candidate]:
    fields = {f.name for f in dictionary.concepts[concept].fields}
    lookup = dictionary.columns[concept]
    if header.strip() in fields:
        return [_Candidate(column, header.strip(), Layer.CANONICAL, 1.0, "canonical name")]
    if token in lookup:
        alias = lookup[token]
        return [_Candidate(column, alias.field, Layer.DICTIONARY, 1.0, f"alias {alias.label!r}")]
    if len(token) < MIN_FUZZY_LENGTH:
        return []
    matches = process.extract(
        token, list(lookup), scorer=fuzz.ratio, score_cutoff=FUZZY_THRESHOLD, limit=None
    )
    best: dict[str, _Candidate] = {}
    for alias_token, score, _ in sorted(matches, key=lambda m: (-m[1], m[0])):
        alias = lookup[alias_token]
        if alias.field not in best and len(alias_token) >= MIN_FUZZY_LENGTH:
            best[alias.field] = _Candidate(
                column, alias.field, Layer.FUZZY, score / 100, f"close to {alias.label!r}"
            )
    return list(best.values())


def map_columns(
    frame: pl.DataFrame,
    headers: tuple[str, ...],
    concept: str,
    dictionary: Dictionary,
    profiles: dict[str, ValueProfile] | None = None,
) -> list[ColumnMapping]:
    """One mapping per header of `frame` for `concept`, in header order."""
    spec = dictionary.concepts[concept]
    profiles = profiles if profiles is not None else {h: profile_values(frame[h]) for h in headers}
    result: dict[int, ColumnMapping] = {}
    candidates: list[_Candidate] = []
    rejected: dict[int, str] = {}
    field_tokens = dictionary.field_tokens
    for i, header in enumerate(headers):
        profile = profiles[header]
        token = normalise_label(header)
        if header.startswith(UNNAMED) or not token:
            what = "empty column" if profile.kind == "empty" else "column"
            result[i] = ColumnMapping(header, None, Layer.NONE, 0.0, f"{what} without a header")
            continue
        names = _name_candidates(i, header, token, concept, dictionary)
        exact = any(c.layer in (Layer.CANONICAL, Layer.DICTIONARY) for c in names)
        exact = exact or token in field_tokens
        personal = personal_kind(token, profile, exact, dictionary)
        if personal is not None:
            kind, evidence = personal
            result[i] = ColumnMapping(header, None, Layer.PERSONAL, 1.0, evidence, kind)
            continue
        for candidate in names:
            field = spec.field(candidate.field)
            assert field is not None
            lookup = dictionary.values.get((concept, field.name))
            check, evidence = value_check(field, profile, frame[header], lookup)
            text = f"{candidate.evidence}; values: {evidence}"
            if check is Check.REJECTED:
                rejected[i] = f"{candidate.field} {candidate.evidence}, rejected: {evidence}"
                continue
            factor = 1.0 if check is Check.CONFIRMED else UNCONFIRMED
            candidates.append(
                replace(candidate, confidence=candidate.confidence * factor, evidence=text)
            )
        if not names and profile.currency_share >= CONFIRM_SHARE and spec.field("currency"):
            candidates.append(
                _Candidate(
                    i,
                    "currency",
                    Layer.VALUES,
                    VALUES_ONLY,
                    f"values: {profile.currency_share:.0%} three-letter codes",
                )
            )
    taken: dict[str, int] = {}
    order = sorted(candidates, key=lambda c: (-c.confidence, _LAYER_RANK[c.layer], c.column))
    for candidate in order:
        if candidate.column in result or candidate.field in taken:
            continue
        taken[candidate.field] = candidate.column
        result[candidate.column] = ColumnMapping(
            headers[candidate.column],
            candidate.field,
            candidate.layer,
            round(candidate.confidence, 3),
            candidate.evidence,
        )
    for i, header in enumerate(headers):
        if i in result:
            continue
        lost = [c for c in candidates if c.column == i]
        if lost:
            winner = headers[taken[lost[0].field]]
            evidence = f"{lost[0].field} already taken by {winner!r}"
        else:
            evidence = rejected.get(i, "no field matches the header")
        result[i] = ColumnMapping(header, None, Layer.NONE, 0.0, evidence)
    return [result[i] for i in range(len(headers))]
