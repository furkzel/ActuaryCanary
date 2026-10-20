"""Tiny reader for benchmark and hand-fixture files.

Returns plain structures only (dicts and lists), so tests need no external package.
"""

import csv
from pathlib import Path
from typing import Any, TypedDict

import yaml

BENCHMARK_DIR = Path(__file__).parent
HAND_DIR = BENCHMARK_DIR.parent / "fixtures" / "hand"


class Triangle(TypedDict):
    origins: list[int]
    ages: list[int]
    values: list[list[float | None]]  # one row per origin, None where not yet observed


def load_triangle(path: Path) -> Triangle:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    ages = [int(a) for a in rows[0][1:]]
    origins: list[int] = []
    values: list[list[float | None]] = []
    for row in rows[1:]:
        origins.append(int(row[0]))
        values.append([float(c) if c.strip() else None for c in row[1:]])
    return {"origins": origins, "ages": ages, "values": values}


def load_premium(path: Path) -> dict[int, float]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {int(r["origin"]): float(r["earned_premium"]) for r in csv.DictReader(handle)}


def load_expected(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def benchmark_names() -> list[str]:
    return sorted(p.parent.name for p in BENCHMARK_DIR.glob("*/expected.yaml"))


def load_benchmark(name: str) -> dict[str, Any]:
    folder = BENCHMARK_DIR / name
    return {
        "triangle": load_triangle(folder / "triangle.csv"),
        "expected": load_expected(folder / "expected.yaml"),
    }


def load_hand() -> dict[str, Any]:
    return {
        "paid": load_triangle(HAND_DIR / "paid_triangle.csv"),
        "incurred": load_triangle(HAND_DIR / "incurred_triangle.csv"),
        "premium": load_premium(HAND_DIR / "premium.csv"),
        "expected": load_expected(HAND_DIR / "expected.yaml"),
    }
