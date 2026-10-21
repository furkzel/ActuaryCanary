"""Concept detection (blueprint 6.2): which data concept a sheet holds, with scores.

Each sheet is scored against every concept by the fields its columns map to (required fields
weigh twice) and by grain: the concept's keys are unique in the sheet. The file and sheet
name are a hint worth a small bonus, never a rule. Candidates are ranked: concepts whose
required fields are all found come first, then by score.
"""

from dataclasses import dataclass

import polars as pl

from actuarycanary.recognition.columns import ColumnMapping, map_columns
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.value_profile import ValueProfile
from actuarycanary.spec.labels import normalise_label

FIELD_WEIGHT = 0.9
GRAIN_BONUS = 0.05
NAME_BONUS = 0.05
UNIQUE_SHARE = 0.98  # share of distinct keys that counts as the concept's grain
MIN_SCORE = 0.3  # below this, and with required fields missing, no concept is proposed


@dataclass(frozen=True)
class ConceptScore:
    concept: str
    score: float
    required: tuple[int, int]  # found, total
    optional: tuple[int, int]
    grain: str
    name_hint: bool
    mappings: tuple[ColumnMapping, ...]

    @property
    def complete(self) -> bool:
        return self.required[0] == self.required[1]

    def detail(self) -> str:
        found = f"required {self.required[0]}/{self.required[1]}"
        found += f", optional {self.optional[0]}/{self.optional[1]}"
        hint = ", name hint" if self.name_hint else ""
        return f"score {self.score:.2f} ({found}; {self.grain}{hint})"

    def describe(self) -> str:
        return f"{self.concept} {self.detail()}"


def missing_required(concept: str, mappings: tuple[ColumnMapping, ...], d: Dictionary) -> list[str]:
    used = {m.field for m in mappings if m.used}
    return [f.name for f in d.concepts[concept].fields if f.required and f.name not in used]


def _grain(frame: pl.DataFrame, keys: list[str], mappings: tuple[ColumnMapping, ...]) -> str:
    if not keys:
        return "no key in the spec"
    source = {m.field: m.source for m in mappings if m.used}
    if any(k not in source for k in keys):
        return "keys not found"
    columns = [source[k] for k in keys]
    rows = frame.select(columns).drop_nulls()
    if rows.height == 0:
        return "keys empty"
    share = rows.n_unique() / rows.height
    verdict = "unique" if share >= UNIQUE_SHARE else "not unique"
    return f"keys {verdict} ({share:.1%} distinct)"


def _name_hint(names: tuple[str, ...], concept: str, d: Dictionary) -> bool:
    spec = d.concepts[concept]
    targets = {normalise_label(t) for t in (spec.id, spec.title_en, spec.title_tr)}
    tokens = {normalise_label(n) for n in names}
    return any(t and t in targets for t in tokens)


def score_concept(
    frame: pl.DataFrame,
    headers: tuple[str, ...],
    names: tuple[str, ...],
    concept: str,
    dictionary: Dictionary,
    profiles: dict[str, ValueProfile],
) -> ConceptScore:
    mappings = tuple(map_columns(frame, headers, concept, dictionary, profiles))
    fields = dictionary.concepts[concept].fields
    used = {m.field for m in mappings if m.used}
    required = sum(f.name in used for f in fields if f.required), sum(f.required for f in fields)
    optional = (
        sum(f.name in used for f in fields if not f.required),
        sum(not f.required for f in fields),
    )
    total = 2 * required[1] + optional[1]
    coverage = (2 * required[0] + optional[0]) / total if total else 0.0
    grain = _grain(frame, dictionary.concepts[concept].keys, mappings)
    hint = _name_hint(names, concept, dictionary)
    score = FIELD_WEIGHT * coverage
    score += GRAIN_BONUS * grain.startswith("keys unique") + NAME_BONUS * hint
    return ConceptScore(concept, round(score, 4), required, optional, grain, hint, mappings)


def score_concepts(
    frame: pl.DataFrame,
    headers: tuple[str, ...],
    names: tuple[str, ...],
    dictionary: Dictionary,
    profiles: dict[str, ValueProfile],
) -> list[ConceptScore]:
    """Every concept's score for one sheet, best first. `names` are the file stem and sheet."""
    scores = [
        score_concept(frame, headers, names, c, dictionary, profiles) for c in dictionary.concepts
    ]
    return sorted(scores, key=lambda s: (not s.complete, -s.score, s.concept))


def best_concept(scores: list[ConceptScore]) -> ConceptScore | None:
    if not scores:
        return None
    best = scores[0]
    return best if best.complete or best.score >= MIN_SCORE else None
