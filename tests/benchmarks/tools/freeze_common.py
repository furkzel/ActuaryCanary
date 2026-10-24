# ruff: noqa: E501
"""Shared writers for the tier B references (manifest.yaml, values.csv, triangle CSVs).

Used by the freeze scripts in this folder; the tests never import it. Every reference folder holds
a manifest.yaml, the input CSVs and a values.csv (quantity, key, value, rel_tol, note) that opens
in a spreadsheet.
"""

import csv
import datetime
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

TIER_B_DIR = Path(__file__).resolve().parents[1] / "tier_b"
HAND_TIER_B_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hand" / "tier_b"

VALUE_COLUMNS = ["quantity", "key", "value", "rel_tol", "note"]


def clean(value: float) -> float:
    """Round-trip safe float for CSV (repr keeps every digit)."""
    return float(value)


def write_values(folder: Path, rows: Iterable[Sequence[Any]]) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    with (folder / "values.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(VALUE_COLUMNS)
        for quantity, key, value, rel_tol, note in rows:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"non-finite value for {quantity}/{key}")
            writer.writerow([quantity, key, repr(float(value)), rel_tol, note])
            count += 1
    return count


def write_triangle(path: Path, origins: Sequence[Any], ages: Sequence[int], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["origin", *ages])
        for origin, row in zip(origins, rows, strict=True):
            writer.writerow([origin, *["" if v is None else repr(float(v)) for v in row]])


def write_table(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


def write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    full = {
        "produced_on": datetime.date.today().isoformat(),
        **manifest,
        "checked_by_owner": False,
    }
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "manifest.yaml").open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(full, handle, sort_keys=False, allow_unicode=True, width=100)
