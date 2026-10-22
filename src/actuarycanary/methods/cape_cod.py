"""Cape Cod (MT04): Bornhuetter–Ferguson with the loss ratio estimated from the data.

One expected loss ratio per triangle: reported claims over the premium already used up by
development, over the origins with positive premium. No trend and no decay.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.bornhuetter_ferguson import premium_axis_reason, premium_reasons
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped


@dataclass(frozen=True)
class CapeCod:
    expected_loss_ratio: float  # ELR(CC)
    premium: np.ndarray
    used_up_premium: np.ndarray  # P(i) / CDF(J_i); NaN for origins not used
    latest: np.ndarray
    ultimate: np.ndarray  # NaN for origins not run
    not_run: dict[int, str]
    chain_ladder_ultimate: np.ndarray

    @property
    def chain_ladder_loss_ratio(self) -> np.ndarray:
        """Chain-ladder ultimate over premium per origin, against ELR(CC) (diagnostic)."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.chain_ladder_ultimate / self.premium


def cape_cod(
    chain: ChainLadder,
    premium: Sequence[float] | np.ndarray,
    *,
    origin_axis: str = "accident",
) -> CapeCod | Skipped:
    """MT04 on the triangle `chain` ran on, with earned premium per origin (NaN if missing)."""
    reason = premium_axis_reason("Cape Cod", origin_axis)
    if reason:
        return Skipped("MT04", reason)
    premium = np.asarray(premium, dtype=float)
    not_run = premium_reasons(premium)
    used = np.ones(len(premium), dtype=bool)
    used[list(not_run)] = False
    if not used.any():
        return Skipped("MT04", "no origin with positive earned premium")
    used_up = np.where(used, premium / chain.cdf_at_latest, np.nan)
    total_used_up = float(used_up[used].sum())
    if total_used_up <= 0:
        return Skipped("MT04", "the used-up premium sums to zero or less")
    elr = float(chain.latest[used].sum()) / total_used_up
    ultimate = chain.latest + (1 - 1 / chain.cdf_at_latest) * elr * premium
    ultimate[~used] = np.nan
    return CapeCod(
        expected_loss_ratio=elr,
        premium=premium,
        used_up_premium=used_up,
        latest=chain.latest,
        ultimate=ultimate,
        not_run=not_run,
        chain_ladder_ultimate=chain.ultimate,
    )
