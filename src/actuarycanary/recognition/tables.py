"""Recognition of one sheet: header row, concept, column mappings, and where they came from.

`recognise_table` proposes; a saved mapping profile (`with_profile`) or the user (`with_concept`,
`with_field`) may change the proposal; `canonical_table` applies it, renaming mapped columns
to their fields, dropping every other column and mapping class labels (AL02). Personal-data
columns are recognised again from the values whatever a profile says, so they never reach a
canonical table.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from pathlib import PurePath

import polars as pl

from actuarycanary.io.excel import SOURCE_COLUMNS, RawTable
from actuarycanary.recognition.columns import ColumnMapping, Layer
from actuarycanary.recognition.concepts import (
    ConceptScore,
    best_concept,
    missing_required,
    score_concepts,
)
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.mapping_profiles import (
    MappingProfile,
    ProfileColumn,
    ProfileError,
    fingerprint,
)
from actuarycanary.recognition.personal import personal_kind
from actuarycanary.recognition.value_profile import ValueProfile, profile_values
from actuarycanary.recognition.values import ValueMapping, map_values
from actuarycanary.spec.labels import normalise_label

CANDIDATES_KEPT = 3


class Source(StrEnum):
    CANONICAL = "canonical"  # every header is a canonical field name; nothing to confirm
    SAVED = "saved"  # a saved mapping profile was applied
    CONFIRMED = "confirmed"  # confirmed by the user in this run and saved
    AUTOMATIC = "automatic"  # proposed and used without confirmation
    SKIPPED = "skipped"  # the user or a profile set no concept


@dataclass(frozen=True)
class TableRecognition:
    file: str
    sheet: str
    header_row: int
    rows_above: int
    header_evidence: str
    headers: tuple[str, ...]
    fingerprint: str
    candidates: tuple[ConceptScore, ...]  # best first
    concept: str | None
    mappings: tuple[ColumnMapping, ...]  # one per header, for `concept`
    source: Source
    profile_sha256: str | None = None
    value_profiles: dict[str, ValueProfile] = field(default_factory=dict, repr=False)

    @property
    def label(self) -> str:
        return f"{self.file} [{self.sheet}]"

    @property
    def personal(self) -> list[ColumnMapping]:
        return [m for m in self.mappings if m.personal is not None]

    def missing(self, dictionary: Dictionary) -> list[str]:
        if self.concept is None:
            return []
        return missing_required(self.concept, self.mappings, dictionary)


def _is_canonical_layout(best: ConceptScore) -> bool:
    named = [m for m in best.mappings if not m.source.startswith("__UNNAMED__")]
    return best.complete and all(m.layer is Layer.CANONICAL for m in named)


def recognise_table(table: RawTable, file: str, dictionary: Dictionary) -> TableRecognition:
    headers = table.headers
    profiles = {h: profile_values(table.frame[h]) for h in headers}
    names = (PurePath(file).stem, table.sheet)
    scores = score_concepts(table.frame, headers, names, dictionary, profiles)
    best = best_concept(scores)
    if best is None:
        mappings = tuple(
            ColumnMapping(h, None, Layer.NONE, 0.0, "no concept recognised") for h in headers
        )
        mappings = _personal_only(mappings, profiles, dictionary)
    else:
        mappings = best.mappings
    canonical = best is not None and _is_canonical_layout(best)
    return TableRecognition(
        file=file,
        sheet=table.sheet,
        header_row=table.header_row,
        rows_above=table.rows_above,
        header_evidence=table.header_evidence,
        headers=headers,
        fingerprint=fingerprint(headers),
        candidates=tuple(scores[:CANDIDATES_KEPT]),
        concept=best.concept if best else None,
        mappings=mappings,
        source=Source.CANONICAL if canonical else Source.AUTOMATIC,
        value_profiles=profiles,
    )


def _personal_only(
    mappings: tuple[ColumnMapping, ...], profiles: dict[str, ValueProfile], d: Dictionary
) -> tuple[ColumnMapping, ...]:
    """Mappings with every personal-data column marked again from header and values."""
    out: list[ColumnMapping] = []
    for m in mappings:
        token = normalise_label(m.source)
        found = personal_kind(token, profiles[m.source], token in d.field_tokens, d)
        if found is None:
            out.append(m if m.personal is None else replace(m, personal=None))
        else:
            out.append(ColumnMapping(m.source, None, Layer.PERSONAL, 1.0, found[1], found[0]))
    return tuple(out)


def with_profile(
    rec: TableRecognition, profile: MappingProfile, sha256: str, dictionary: Dictionary
) -> TableRecognition:
    """The recognition with a saved profile's concept and fields."""
    if profile.concept is None:
        return replace(rec, concept=None, source=Source.SKIPPED, profile_sha256=sha256)
    if profile.concept not in dictionary.concepts:
        raise ProfileError(f"profile {profile.fingerprint}: unknown concept {profile.concept!r}")
    spec = dictionary.concepts[profile.concept]
    mappings: list[ColumnMapping] = []
    for header in rec.headers:
        target = profile.field_of(header)
        if target is not None and spec.field(target) is None:
            raise ProfileError(
                f"profile {profile.fingerprint}: {target!r} is not a field of {profile.concept}"
            )
        evidence = f"saved profile {profile.fingerprint}"
        if target is None:
            mappings.append(ColumnMapping(header, None, Layer.NONE, 0.0, f"ignored in {evidence}"))
        else:
            mappings.append(ColumnMapping(header, target, Layer.SAVED, 1.0, evidence))
    checked = _personal_only(tuple(mappings), rec.value_profiles, dictionary)
    return replace(
        rec, concept=profile.concept, mappings=checked, source=Source.SAVED, profile_sha256=sha256
    )


def with_concept(
    rec: TableRecognition, concept: str | None, table: RawTable, dictionary: Dictionary
) -> TableRecognition:
    """The recognition for another concept (None: skip the sheet), mapped again."""
    if concept is None:
        return replace(rec, concept=None, source=Source.SKIPPED)
    if concept not in dictionary.concepts:
        raise ValueError(f"unknown concept {concept!r}")
    names = (PurePath(rec.file).stem, rec.sheet)
    scores = score_concepts(table.frame, rec.headers, names, dictionary, rec.value_profiles)
    chosen = next(s for s in scores if s.concept == concept)
    return replace(rec, concept=concept, mappings=chosen.mappings, source=Source.AUTOMATIC)


def with_field(
    rec: TableRecognition, header: str, target: str | None, dictionary: Dictionary
) -> TableRecognition:
    """The recognition with `header` mapped to `target` by the user (None: not used)."""
    if rec.concept is None:
        raise ValueError("choose a concept first")
    if header not in rec.headers:
        raise ValueError(f"no column {header!r}")
    if target is not None and dictionary.concepts[rec.concept].field(target) is None:
        raise ValueError(f"{target!r} is not a field of {rec.concept}")
    mappings: list[ColumnMapping] = []
    for m in rec.mappings:
        if m.source == header:
            if m.personal is not None:
                raise ValueError(f"{header!r} holds personal data and is always dropped")
            if target is None:
                mappings.append(ColumnMapping(header, None, Layer.USER, 1.0, "not used (user)"))
            else:
                mappings.append(ColumnMapping(header, target, Layer.USER, 1.0, "set by user"))
        elif target is not None and m.field == target:
            mappings.append(
                ColumnMapping(m.source, None, Layer.USER, 1.0, f"{target} moved to {header!r}")
            )
        else:
            mappings.append(m)
    return replace(rec, mappings=tuple(mappings))


def to_profile(rec: TableRecognition, confirmed_on: date) -> MappingProfile:
    columns = [
        ProfileColumn(
            header=m.source,
            field=m.field if m.used else None,
            layer=str(m.layer),
            confidence=m.confidence,
            evidence=m.evidence,
        )
        for m in rec.mappings
    ]
    return MappingProfile(
        fingerprint=rec.fingerprint,
        concept=rec.concept,
        confirmed_on=confirmed_on,
        headers=list(rec.headers),
        columns=columns,
    )


def canonical_table(
    table: RawTable, rec: TableRecognition, dictionary: Dictionary
) -> tuple[RawTable, list[ValueMapping]]:
    """The sheet with mapped columns renamed to their fields and nothing else but the source
    columns; class labels mapped to classes."""
    if rec.concept is None:
        raise ValueError(f"{rec.label} has no concept")
    used = [m for m in rec.mappings if m.used]
    frame = table.frame.select(
        *(pl.col(m.source).alias(m.field) for m in used if m.field), *SOURCE_COLUMNS
    )
    frame, values = map_values(frame, rec.concept, dictionary)
    return replace(table, frame=frame), values
