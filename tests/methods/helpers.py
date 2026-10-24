"""Shared helpers of the method tests: triangles as arrays and labels of the hand fixture."""

import numpy as np
import polars as pl

from actuarycanary.methods.chain_ladder import ChainLadder, chain_ladder
from actuarycanary.methods.robust_z import RESERVE_VARIABLES, RobustZ
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


def reserve_flag_shares(result: RobustZ) -> dict[str, float]:
    """Flagged share of the reserve movements of each line, over the groups that were scored."""
    rates = result.flag_rates.filter(
        pl.col("variable").is_in(RESERVE_VARIABLES) & (pl.col("status") == "scored")
    )
    by_line = rates.group_by("line").agg(pl.col("values").sum(), pl.col("flagged").sum())
    return {r["line"]: r["flagged"] / r["values"] for r in by_line.iter_rows(named=True)}
