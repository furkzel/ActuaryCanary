"""Value recognition (blueprint 6.4): class labels mapped through the value aliases (AL02).

Each label is normalised and looked up; a label that matches no class becomes UNMAPPED and is
listed with its row count, never dropped or guessed. Empty labels stay empty.
"""

from dataclasses import dataclass

import polars as pl

from actuarycanary.canonical.feeds import UNMAPPED
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.spec.labels import normalise_label


@dataclass(frozen=True)
class ValueMapping:
    field: str
    mapped: tuple[tuple[str, str, int], ...]  # (label, class, rows), labels that differ
    unmapped: tuple[tuple[str, int], ...]  # (label, rows)

    @property
    def unmapped_rows(self) -> int:
        return sum(n for _, n in self.unmapped)


def map_labels(series: pl.Series, lookup: dict[str, str]) -> tuple[pl.Series, ValueMapping]:
    stripped = pl.col(series.name).cast(pl.String).str.strip_chars()
    text = series.to_frame().select(pl.when(stripped == "").then(None).otherwise(stripped))
    text = text.to_series()
    counts = text.drop_nulls().value_counts(sort=False)
    classes: dict[str, str] = {}
    mapped: list[tuple[str, str, int]] = []
    unmapped: list[tuple[str, int]] = []
    for label, rows in counts.iter_rows():
        found = lookup.get(normalise_label(label))
        classes[label] = found or UNMAPPED
        if found is None:
            unmapped.append((label, rows))
        elif found != label:
            mapped.append((label, found, rows))
    out = text.replace_strict(classes, default=None, return_dtype=pl.String) if classes else text
    report = ValueMapping(
        series.name,
        tuple(sorted(mapped, key=lambda m: (-m[2], m[0]))),
        tuple(sorted(unmapped, key=lambda m: (-m[1], m[0]))),
    )
    return out.alias(series.name), report


def map_values(
    frame: pl.DataFrame, concept: str, dictionary: Dictionary
) -> tuple[pl.DataFrame, list[ValueMapping]]:
    """Classified fields of `frame` (canonical names) with their labels replaced by classes."""
    reports: list[ValueMapping] = []
    columns: list[pl.Series] = []
    for field in dictionary.concepts[concept].fields:
        lookup = dictionary.values.get((concept, field.name))
        if lookup is None or field.name not in frame.columns:
            continue
        values, report = map_labels(frame[field.name], lookup)
        columns.append(values)
        reports.append(report)
    return (frame.with_columns(columns) if columns else frame), reports
