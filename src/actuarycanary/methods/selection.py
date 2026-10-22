"""Ultimate selection (MT10): chain ladder for developed origins, Bornhuetter–Ferguson for
immature ones, unless an override in the assumptions register says otherwise."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped

BF_BELOW_MATURITY = 0.5  # record 0011


class Choice(StrEnum):
    CHAIN_LADDER = "chain_ladder"
    BORNHUETTER_FERGUSON = "bornhuetter_ferguson"


@dataclass(frozen=True)
class Selection:
    maturity: np.ndarray  # m(i) = 1 / CDF(J_i)
    method: tuple[Choice, ...]
    why: tuple[str, ...]
    ultimate: np.ndarray

    def unpaid(self, paid: np.ndarray) -> np.ndarray:
        return self.ultimate - paid

    def ibnr(self, incurred: np.ndarray) -> np.ndarray:
        return self.ultimate - incurred


def select_ultimates(
    chain: ChainLadder | Skipped,
    bf: BornhuetterFerguson | Skipped | None,
    *,
    bf_below_maturity: float = BF_BELOW_MATURITY,
    overrides: Mapping[int, Choice] | None = None,
) -> Selection | Skipped:
    """MT10 on one triangle. `overrides` maps origin index to the method chosen by the user."""
    if isinstance(chain, Skipped):
        return Skipped("MT10", chain.reason)
    overrides = overrides or {}
    maturity = 1 / chain.cdf_at_latest
    methods: list[Choice] = []
    why: list[str] = []
    ultimate = chain.ultimate.copy()
    for i, m in enumerate(maturity):
        bf_value = np.nan if not isinstance(bf, BornhuetterFerguson) else bf.ultimate[i]
        if isinstance(bf, Skipped):
            bf_reason = bf.reason
        elif bf is None:
            bf_reason = "Bornhuetter–Ferguson did not run"
        else:
            bf_reason = bf.not_run.get(i, "")
        wanted = overrides.get(i)
        if wanted is not None:
            reason = "override in the assumptions register"
        elif m < bf_below_maturity:
            wanted = Choice.BORNHUETTER_FERGUSON
            reason = f"maturity {m:.3f} below {bf_below_maturity}"
        else:
            wanted = Choice.CHAIN_LADDER
            reason = f"maturity {m:.3f} at least {bf_below_maturity}"
        if wanted is Choice.BORNHUETTER_FERGUSON and not np.isfinite(bf_value):
            wanted = Choice.CHAIN_LADDER
            reason += (
                f"; chain ladder used because Bornhuetter–Ferguson is not available: {bf_reason}"
            )
        if wanted is Choice.BORNHUETTER_FERGUSON:
            ultimate[i] = bf_value
        methods.append(wanted)
        why.append(reason)
    return Selection(maturity, tuple(methods), tuple(why), ultimate)
