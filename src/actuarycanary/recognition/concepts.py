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
    """The best candidate if it is a proposal at all (the older, weaker test: all required fields
    found, or a score of at least MIN_SCORE). `judge` adds the positive-evidence rule."""
    if not scores:
        return None
    best = scores[0]
    return best if best.complete or best.score >= MIN_SCORE else None


# Positive evidence (record 0375). Measured on every sheet of the six known feeds and of the
# interest rates in the clean and the messy scenarios (margin 0.32 or more, required share 0.83
# or more, explained share 0.88 or more) and on the planned feeds (reinsurance treaties and
# transactions, recoveries, ledger, life feeds; margin 0.00 to 0.35, explained share 0.27 to 0.71).
MIN_MARGIN = 0.30  # the best score must be above the next concept's by more than this
CLEAR_MARGIN = 0.50  # above this margin the extra columns of a sheet do not matter
MIN_REQUIRED_SHARE = 0.80  # share of the concept's required fields found
MIN_EXPLAINED_SHARE = 0.75  # share of the sheet's columns that map to a field or are personal


@dataclass(frozen=True)
class Verdict:
    accepted: ConceptScore | None
    best_guess: ConceptScore | None
    margin: float
    required_share: float
    explained_share: float
    reasons: tuple[str, ...]  # why the best guess was rejected; empty when accepted

    def explain(self) -> str:
        """For a sheet that was not recognised: the best guess and why it was rejected."""
        if self.best_guess is None:
            return "no concept recognised"
        return f"best guess {self.best_guess.describe()}, rejected: " + "; ".join(self.reasons)


def judge(scores: list[ConceptScore]) -> Verdict:
    """Accept the best concept only on positive evidence, otherwise say why not.

    Accepted when (1) the best score is above the next concept's by more than MIN_MARGIN, (2) at
    least MIN_REQUIRED_SHARE of its required fields are found, and (3) either the margin is at
    least CLEAR_MARGIN or at least MIN_EXPLAINED_SHARE of the sheet's columns map to a field of
    the concept or are personal-data columns. A workbook that merely resembles a known concept
    (it has its required columns and a dozen more) is listed as not recognised instead.
    """
    if not scores:
        return Verdict(None, None, 0.0, 0.0, 0.0, ("the sheet has no columns",))
    best = scores[0]
    second = scores[1].score if len(scores) > 1 else 0.0
    margin = round(best.score - second, 4)
    required_share = best.required[0] / best.required[1] if best.required[1] else 0.0
    columns = best.mappings
    explained = sum(m.used or m.personal is not None for m in columns)
    explained_share = explained / len(columns) if columns else 0.0
    reasons: list[str] = []
    if best_concept(scores) is None:
        reasons.append(f"score {best.score:.2f} is below {MIN_SCORE} with required fields missing")
    if margin <= MIN_MARGIN:
        reasons.append(f"margin {margin:.2f} over the next concept is not above {MIN_MARGIN}")
    if required_share < MIN_REQUIRED_SHARE:
        reasons.append(
            f"required fields found {best.required[0]}/{best.required[1]}, "
            f"under {MIN_REQUIRED_SHARE:.0%}"
        )
    if margin < CLEAR_MARGIN and explained_share < MIN_EXPLAINED_SHARE:
        reasons.append(
            f"only {explained} of {len(columns)} columns are explained by the concept, "
            f"under {MIN_EXPLAINED_SHARE:.0%}"
        )
    accepted = None if reasons else best
    return Verdict(accepted, best, margin, required_share, explained_share, tuple(reasons))
