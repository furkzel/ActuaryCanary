"""Bornhuetter–Ferguson (MT03): reported claims plus the unreported share of a prior ultimate.

The unreported share comes from the chain-ladder pattern of the same triangle (MT02 selected
factors); the prior is a loss ratio times earned premium of the origin.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.chain_ladder import ChainLadder, Skipped

PREMIUM_AXES = ("accident", "underwriting")  # origins that earned premium can be matched to
USER_PRIOR = "user"
DATA_DERIVED_PRIOR = "data-derived prior"


def premium_axis_reason(method: str, origin_axis: str) -> str | None:
    """Why a premium-based method cannot run on this origin axis, or None when it can."""
    if origin_axis in PREMIUM_AXES:
        return None
    return f"{method} needs accident or underwriting origins matched to earned premium"


def premium_reasons(premium: np.ndarray) -> dict[int, str]:
    """Origins whose earned premium is missing, zero or negative, with the reason."""
    reasons: dict[int, str] = {}
    for i, p in enumerate(premium):
        if not np.isfinite(p):
            reasons[i] = "earned premium missing"
        elif p <= 0:
            reasons[i] = f"earned premium {p:g} is not positive"
    return reasons


@dataclass(frozen=True)
class BornhuetterFerguson:
    premium: np.ndarray  # P(i)
    prior_loss_ratio: np.ndarray  # ELR(i); NaN where none is available
    prior_source: tuple[str, ...]  # per origin: user or data-derived prior
    prior_ultimate: np.ndarray  # ELR(i) P(i)
    percent_unreported: np.ndarray  # q(i) = 1 - 1 / CDF(J_i)
    latest: np.ndarray  # C(i, J_i)
    ultimate: np.ndarray  # NaN for origins not run
    not_run: dict[int, str]  # origin index: reason
    negative_unreported: np.ndarray  # bool: CDF below 1, computed as given and flagged
    chain_ladder_ultimate: np.ndarray

    @property
    def implied_loss_ratio(self) -> np.ndarray:
        """Ultimate over earned premium, next to the prior (diagnostic)."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.ultimate / self.premium

    @property
    def difference_to_chain_ladder(self) -> np.ndarray:
        return self.ultimate - self.chain_ladder_ultimate


def bornhuetter_ferguson(
    chain: ChainLadder,
    premium: Sequence[float] | np.ndarray,
    prior_loss_ratio: Sequence[float] | np.ndarray | float,
    *,
    prior_source: Sequence[str] | str = USER_PRIOR,
    origin_axis: str = "accident",
) -> BornhuetterFerguson | Skipped:
    """MT03 on the triangle `chain` ran on. `premium` and `prior_loss_ratio` are per origin
    (NaN where missing); one prior may be given for all origins."""
    reason = premium_axis_reason("Bornhuetter–Ferguson", origin_axis)
    if reason:
        return Skipped("MT03", reason)
    premium = np.asarray(premium, dtype=float)
    n = len(chain.latest)
    prior = np.broadcast_to(np.asarray(prior_loss_ratio, dtype=float), (n,)).copy()
    sources = (prior_source,) * n if isinstance(prior_source, str) else tuple(prior_source)
    if not np.isfinite(prior).any():
        return Skipped("MT03", "no prior loss ratio available")

    not_run = premium_reasons(premium)
    for i in np.flatnonzero(~np.isfinite(prior)):
        not_run.setdefault(int(i), "no prior loss ratio available")
    q = 1 - 1 / chain.cdf_at_latest
    prior_ultimate = prior * premium
    ultimate = chain.latest + q * prior_ultimate
    ultimate[list(not_run)] = np.nan
    return BornhuetterFerguson(
        premium=premium,
        prior_loss_ratio=prior,
        prior_source=sources,
        prior_ultimate=prior_ultimate,
        percent_unreported=q,
        latest=chain.latest,
        ultimate=ultimate,
        not_run=dict(sorted(not_run.items())),
        negative_unreported=q < 0,
        chain_ladder_ultimate=chain.ultimate,
    )
