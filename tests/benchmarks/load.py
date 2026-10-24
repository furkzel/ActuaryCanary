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
    loaded = {
        "triangle": load_triangle(folder / "triangle.csv"),
        "expected": load_expected(folder / "expected.yaml"),
    }
    if (folder / "premium.csv").exists():
        loaded["premium"] = load_premium(folder / "premium.csv")
    return loaded


def load_hand() -> dict[str, Any]:
    return {
        "paid": load_triangle(HAND_DIR / "paid_triangle.csv"),
        "incurred": load_triangle(HAND_DIR / "incurred_triangle.csv"),
        "premium": load_premium(HAND_DIR / "premium.csv"),
        "expected": load_expected(HAND_DIR / "expected.yaml"),
    }


# --- tier B references (decisions 0270-0279) -------------------------------------------

TIER_B_DIR = BENCHMARK_DIR / "tier_b"
HAND_TIER_B_DIR = HAND_DIR / "tier_b"


class RefValue(TypedDict):
    value: float
    rel_tol: float
    note: str


def tier_b_folders() -> list[Path]:
    """Every folder with a manifest.yaml: library and external references, then hand fixtures."""
    found = [
        p.parent for root in (TIER_B_DIR, HAND_TIER_B_DIR) for p in root.glob("*/manifest.yaml")
    ]
    return sorted(found, key=lambda p: (p.parent.name, p.name))


def tier_b_names() -> list[str]:
    return [folder.name for folder in tier_b_folders()]


def tier_b_folder(name: str) -> Path:
    for folder in tier_b_folders():
        if folder.name == name:
            return folder
    raise KeyError(name)


def load_values(folder: Path) -> dict[tuple[str, str], RefValue]:
    """values.csv as {(quantity, key): {value, rel_tol, note}}; keys stay text (origins, ages)."""
    table: dict[tuple[str, str], RefValue] = {}
    with (folder / "values.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["quantity"], row["key"])
            if key in table:
                raise ValueError(f"{folder.name}: duplicate row {key}")
            table[key] = {
                "value": float(row["value"]),
                "rel_tol": float(row["rel_tol"]),
                "note": row["note"],
            }
    return table


def load_reference(name: str) -> dict[str, Any]:
    """Manifest, values and folder of one tier B reference (plain dicts, no external package)."""
    folder = tier_b_folder(name)
    return {
        "folder": folder,
        "manifest": load_expected(folder / "manifest.yaml"),
        "values": load_values(folder),
    }


def reference_series(values: dict[tuple[str, str], RefValue], quantity: str) -> dict[str, float]:
    """The rows of one quantity as {key: value}, in file order."""
    return {key: row["value"] for (q, key), row in values.items() if q == quantity}


def load_table(path: Path) -> list[dict[str, str]]:
    """A small input CSV (header row, text cells) as a list of dicts."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
