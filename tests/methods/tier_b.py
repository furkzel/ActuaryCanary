"""Shared helpers of the tier B method tests: references as arrays and series."""

import numpy as np

from tests.benchmarks.load import load_reference, load_table, load_triangle, reference_series
from tests.methods.helpers import array


def reference(name: str) -> dict:
    return load_reference(name)


def triangle(name: str, file: str = "triangle.csv") -> tuple[np.ndarray, list[str], list[int]]:
    """(array, origins, ages) of a reference triangle file."""
    loaded = load_triangle(reference(name)["folder"] / file)
    return array(loaded), [str(o) for o in loaded["origins"]], loaded["ages"]


def series(name: str, quantity: str) -> np.ndarray:
    return np.array(list(reference_series(reference(name)["values"], quantity).values()))


def value(name: str, quantity: str, key: str) -> float:
    return reference(name)["values"][(quantity, key)]["value"]


def table(name: str, file: str) -> list[dict[str, str]]:
    return load_table(reference(name)["folder"] / file)
