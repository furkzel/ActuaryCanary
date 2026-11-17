"""The scope of every table and headline of the report (record 0815).

Segments are never added together (spec/data/claims.yaml, MT01, MT09, RP01). A page body
therefore declares, for each of its tables, the level its figures stand for:

- `segment`: every row belongs to exactly one segment (lines inside a segment are fine); the
  row names its segment in a `segment` field or in its `line` as "SEGMENT · LINE".
- `company`: the figure is booked at company level, all segments, because its source is (the
  treaties and programmes of M08, expenses booked without a line on M09). The page says so.
- `entity`: the figure is by legal entity; the books carry no segment (the ledger of M10).
- `info`: not a business figure: files, rules, methods, diagnostics, the settings of a run.

A body holds its declarations in `scopes`, a mapping from the path of a table in the body
(`origins`, `survival.lines`; a nested table belongs to the declaration of its parent) to the
declaration `declare` makes. A table without a declaration fails `tests/report/test_scope.py`;
there is no default.
"""

from typing import Any

from actuarycanary.report.language import t

SEGMENT = "segment"
COMPANY = "company"
ENTITY = "entity"
INFO = "info"
LEVELS = (SEGMENT, COMPANY, ENTITY, INFO)
LABELS = {
    COMPANY: "booked at company level, all segments",
    ENTITY: "by legal entity; the books carry no segment",
}
SEGMENT_SEPARATORS = (" · ", " / ")


def declare(title: str, level: str, note: str = "") -> dict[str, Any]:
    """The declaration of one table: its title, its level, the label the page shows for a
    company- or entity-level table, and the reason when the level is not obvious."""
    if level not in LEVELS:
        raise ValueError(f"unknown scope level {level!r}")
    return {
        "title": t(title),
        "level": level,
        "label": t(LABELS[level]) if level in LABELS else "",
        "note": note,
    }


def segment_of(row: Any, segments: set[str]) -> set[str]:
    """The segments a row names in its `segment`, `line` or `name` field."""
    named: set[str] = set()
    if not isinstance(row, dict):
        return named
    for key in ("segment", "line", "name"):
        text = row.get(key)
        if not isinstance(text, str):
            continue
        for part in text.replace(" / ", " · ").split(" · "):
            if part in segments:
                named.add(part)
    return named
