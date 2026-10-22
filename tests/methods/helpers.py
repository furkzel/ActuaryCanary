"""Shared helpers of the method tests: triangles as arrays and labels of the hand fixture."""

import numpy as np

from actuarycanary.methods.chain_ladder import ChainLadder, chain_ladder
from tests.benchmarks.load import Triangle, load_hand

HAND = load_hand()
HAND_ORIGINS = [str(o) for o in HAND["expected"]["origins"]]
HAND_AGES = HAND["expected"]["ages"]
HAND_PREMIUM = np.array(HAND["expected"]["earned_premium"], dtype=float)


def array(triangle: Triangle) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in triangle["values"]])


def fitted(cumulative: np.ndarray, **options) -> ChainLadder:
    result = chain_ladder(cumulative, **options)
    assert isinstance(result, ChainLadder)
    return result


def values(items: list[dict]) -> list[float]:
    """The `value` of each item of a hand-fixture list."""
    return [item["value"] for item in items]
