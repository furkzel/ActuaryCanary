"""The walk behind the scope guard (record 0815): every table of the report model must name its
scope, and a table cut by segment must not mix segments.

A table is a list of dicts at any depth of a page body, of `reserving` or of the model. Its
declaration is in the `scopes` of the page (or of the model) under the table's dotted path; a
nested table belongs to the declaration of its parent. A table of scope `segment` has rows that
each name one segment (in `segment`, `line` or `name`; a row nested under such a row inherits
the segment). A table of scope `company` or `entity` carries the label the page shows.
"""

from typing import Any

from actuarycanary.report.scope import COMPANY, ENTITY, LEVELS, SEGMENT, segment_of

RUN_SCOPES = ("run", "segment", "line")


def _is_table(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(x, dict) for x in value)


def _tables(node: Any, path: str = ""):
    """Yield (path, rows) of every table below `node`; a plotly figure is not a table."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "scopes" or (key == "figures" and isinstance(value, dict)):
                continue
            yield from _tables(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        if _is_table(node):
            yield path, node
        for row in node:
            if isinstance(row, dict):
                for key, value in row.items():
                    yield from _tables(value, f"{path}.{key}" if path else key)


def _declaration(path: str, scopes: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    parts = path.split(".")
    for end in range(len(parts), 0, -1):
        key = ".".join(parts[:end])
        if key in scopes:
            return key, scopes[key]
    return None


def _check_segment_rows(
    path: str, rows: list[dict[str, Any]], segments: set[str], inherited: frozenset[str]
) -> list[str]:
    problems = []
    for index, row in enumerate(rows):
        own = segment_of(row, segments)
        if len(own) > 1:
            problems.append(f"{path}[{index}] names {sorted(own)}: a row mixes segments")
        elif not own and not inherited and not any(_is_table(v) for v in row.values()):
            problems.append(f"{path}[{index}] names no segment: {str(row)[:80]}")
        below = frozenset(own) or inherited
        for key, value in row.items():
            if _is_table(value):
                problems += _check_segment_rows(f"{path}.{key}", value, segments, below)
    return problems


def check(body: dict[str, Any], segments: set[str], where: str) -> list[str]:
    """The problems of one page body, the reserving page or the model: tables without a
    declaration, declarations of an unknown level, labels missing, and segment tables whose
    rows mix segments or name none."""
    scopes = body.get("scopes", {})
    problems: list[str] = []
    walked: list[str] = []  # tables whose rows (and the tables nested in them) were walked
    for path, rows in _tables(body):
        found = _declaration(path, scopes)
        if found is None:
            problems.append(f"{where}: table {path} has no scope")
            continue
        key, declared = found
        if declared["level"] not in LEVELS:
            problems.append(f"{where}: table {key} has the unknown level {declared['level']}")
        if declared["level"] in (COMPANY, ENTITY) and not declared["label"]:
            problems.append(f"{where}: table {key} is {declared['level']} level without a label")
        if declared["level"] == SEGMENT and not any(path.startswith(w + ".") for w in walked):
            walked.append(path)
            problems += [
                f"{where}: {p}" for p in _check_segment_rows(path, rows, segments, frozenset())
            ]
    return problems


def check_model(model: dict[str, Any]) -> list[str]:
    segments = {str(t["segment"]) for t in model["tiles"]}
    rest = {k: v for k, v in model.items() if k not in ("pages", "reserving")}
    problems = check(rest, segments, "model") + check(model["reserving"], segments, "reserving")
    for page in model["pages"]:
        problems += check(page["body"], segments, page["module"])
    # a key finding is a sentence with its own scope; a segment or line sentence names one segment
    for name in ("key_findings", "further_findings"):
        for row in model[name]:
            if row["scope"] not in RUN_SCOPES:
                problems.append(f"{name}: {row['rule']} has the scope {row['scope']!r}")
            elif row["scope"] != "run" and len(segment_of({"line": row["key"]}, segments)) != 1:
                problems.append(f"{name}: {row['rule']} ({row['scope']}) names no one segment")
    return problems
