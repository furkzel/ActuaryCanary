"""Cell comparison for the golden test (decision 0627).

The golden copy holds the SHA-256 and size of every output file, except the files of
`TOLERANCE_FILES`: for those it holds the cells, and the test compares them after reading.
"""

import copy
import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Optimiser-based outputs of MT17 and MT18 whose last digits depend on the platform: the
# standard errors come from a central-difference Hessian that turns one last bit of the
# log-likelihood into 1e-6 to 1e-5, and a flat likelihood (Pareto II) moves the estimate itself,
# so rounding to ten digits cannot make their bytes equal (records 0626 and 0627). Every other
# file keeps its hash and size. When the severity fits get an analytic Hessian and a tighter
# convergence (a later hardening item), this list becomes empty again.
TOLERANCE_FILES: tuple[str, ...] = (
    "severity_parameters.csv",
    "severity_fits.csv",
    "severity_plots.csv",
)

RELATIVE_TOLERANCE = 1e-4
ABSOLUTE_TOLERANCE = 1e-12
SHOWN = 8  # differences listed in a failure message


@dataclass
class Comparison:
    """What differs between a stored table and the current one."""

    problems: list[str] = field(default_factory=list)
    largest_relative: float = 0.0  # over the numeric cells, 0 when they are equal

    @property
    def equal(self) -> bool:
        return not self.problems


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def table_record(text: str) -> dict[str, Any]:
    """The golden form of a csv text: its column names and one csv line per row."""
    header, *rows = _rows(text)
    lines = []
    for row in rows:
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="").writerow(row)
        lines.append(buffer.getvalue())
    return {"columns": header, "rows": lines}


def table_record_of(path: Path) -> dict[str, Any]:
    return table_record(path.read_text(encoding="utf-8"))


def _number(cell: str) -> float | None:
    try:
        return float(cell)
    except ValueError:
        return None


def _relative(a: float, b: float) -> float:
    scale = max(abs(a), abs(b))
    return 0.0 if scale == 0.0 or a == b else abs(a - b) / scale


def compare_tables(stored: dict[str, Any], current: dict[str, Any]) -> Comparison:
    """Column names and text cells must be equal; numeric cells within the tolerances."""
    result = Comparison()
    if stored["columns"] != current["columns"]:
        result.problems.append(f"columns {stored['columns']} against {current['columns']}")
        return result
    columns = stored["columns"]
    if len(stored["rows"]) != len(current["rows"]):
        result.problems.append(f"{len(stored['rows'])} rows against {len(current['rows'])}")
        return result
    for index, (old_line, new_line) in enumerate(zip(stored["rows"], current["rows"], strict=True)):
        old, new = _rows(old_line)[0], _rows(new_line)[0]
        if len(old) != len(new) or len(old) != len(columns):
            result.problems.append(f"row {index + 1}: {len(old)} cells against {len(new)}")
            continue
        for column, a, b in zip(columns, old, new, strict=True):
            x, y = _number(a), _number(b)
            if x is None or y is None:
                if a != b:
                    result.problems.append(f"row {index + 1}, {column}: {a!r} against {b!r}")
            elif math.isnan(x) or math.isnan(y):
                if not (math.isnan(x) and math.isnan(y)):
                    result.problems.append(f"row {index + 1}, {column}: {a} against {b}")
            elif math.isinf(x) or math.isinf(y):
                if x != y:
                    result.problems.append(f"row {index + 1}, {column}: {a} against {b}")
            else:
                difference = _relative(x, y)
                if abs(x - y) > ABSOLUTE_TOLERANCE:
                    result.largest_relative = max(result.largest_relative, difference)
                if not math.isclose(x, y, rel_tol=RELATIVE_TOLERANCE, abs_tol=ABSOLUTE_TOLERANCE):
                    result.problems.append(
                        f"row {index + 1}, {column}: {a} against {b} (relative {difference:.2e})"
                    )
    return result


def with_tables(model: dict[str, Any], folder: Path) -> dict[str, Any]:
    """`model` with the hash and size of each tolerance file replaced by its cells."""
    model = copy.deepcopy(model)
    found = set()
    for entry in model["reproducibility"]["outputs"]:
        if entry["name"] in TOLERANCE_FILES:
            del entry["size"], entry["sha256"]
            entry.update(table_record_of(folder / entry["name"]))
            found.add(entry["name"])
    missing = set(TOLERANCE_FILES) - found
    assert not missing, f"the run did not write {sorted(missing)}"
    return model


def split_tables(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """(the model without the cells, the cells by file name)."""
    model = copy.deepcopy(model)
    tables = {}
    for entry in model["reproducibility"]["outputs"]:
        if entry["name"] in TOLERANCE_FILES and "rows" in entry:
            tables[entry["name"]] = {"columns": entry.pop("columns"), "rows": entry.pop("rows")}
    return model, tables


def differences(stored: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Why two golden models differ; empty when they agree under the tolerances."""
    old, old_tables = split_tables(stored)
    new, new_tables = split_tables(current)
    found = []
    if old != new:
        found.append("the report data differs outside the tolerance files")
    if set(old_tables) != set(new_tables):
        found.append(f"tables {sorted(old_tables)} against {sorted(new_tables)}")
    for name in sorted(set(old_tables) & set(new_tables)):
        comparison = compare_tables(old_tables[name], new_tables[name])
        found += [f"{name}: {p}" for p in comparison.problems[:SHOWN]]
    return found
