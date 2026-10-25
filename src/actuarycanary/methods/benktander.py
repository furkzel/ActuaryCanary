"""Benktander blends (MT13): iterated Bornhuetter–Ferguson between the prior and the chain ladder.

The reported share comes from the chain-ladder pattern of the same triangle (MT02 selected
factors); the prior ultimate is the one of Bornhuetter–Ferguson (MT03) or of Cape Cod (MT04).
k iterations from the prior give the classical Benktander estimate for k = 1, Bornhuetter–
Ferguson for k = 0 and approach the chain ladder as k grows.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson
from actuarycanary.methods.cape_cod import CapeCod
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.diagnostics import WARNING, Diagnostic

ITERATIONS = 1  # MT13 default: the classical Benktander estimate


class Prior(StrEnum):
    BORNHUETTER_FERGUSON = "MT03"
    CAPE_COD = "MT04"


@dataclass(frozen=True)
class Benktander:
    iterations: int  # k
    prior: Prior
    reported_share: np.ndarray  # p(i) = 1 / CDF(J_i)
    unreported_share: np.ndarray  # q(i) = 1 - p(i)
    prior_ultimate: np.ndarray  # U0(i); NaN where none is available
    latest: np.ndarray
    chain_ladder_ultimate: np.ndarray
    bornhuetter_ferguson_ultimate: np.ndarray  # C + q U0
    ultimate: np.ndarray  # the blend; NaN for origins not run
    weight: np.ndarray  # on the chain ladder, 1 - q^k, capped at 1
    capped: np.ndarray  # bool: CDF below 1 and 1 - q^k above 1; weight 1, chain ladder used
    not_run: dict[int, str]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def reserve(self) -> np.ndarray:
        return self.ultimate - self.latest

    def comparison(self) -> dict[str, np.ndarray]:
        """Chain ladder, Bornhuetter–Ferguson and the blend per origin (MT13 output)."""
        return {
            "chain_ladder": self.chain_ladder_ultimate,
            "bornhuetter_ferguson": self.bornhuetter_ferguson_ultimate,
            "benktander": self.ultimate,
        }


def prior_ultimate(source: BornhuetterFerguson | CapeCod) -> np.ndarray:
    """U0(i) of MT03 (prior loss ratio times premium) or MT04 (ELR(CC) times premium)."""
    if isinstance(source, BornhuetterFerguson):
        return source.prior_ultimate.copy()
    return source.expected_loss_ratio * source.premium


def benktander(
    chain: ChainLadder | Skipped,
    prior: BornhuetterFerguson | CapeCod | Skipped | Sequence[float] | np.ndarray,
    *,
    iterations: int = ITERATIONS,
    prior_source: Prior = Prior.BORNHUETTER_FERGUSON,
    origins: Sequence[str] | None = None,
) -> Benktander | Skipped:
    """MT13 on the triangle `chain` ran on. `prior` is the MT03 or MT04 result, or the prior
    ultimate per origin (NaN where missing)."""
    if isinstance(chain, Skipped):
        return Skipped("MT13", chain.reason)
    if isinstance(prior, Skipped):
        return Skipped("MT13", prior.reason)
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 0:
        raise ValueError(f"Benktander iterations {iterations!r} must be a whole number >= 0")
    if isinstance(prior, BornhuetterFerguson | CapeCod):
        u0 = prior_ultimate(prior)
    else:
        u0 = np.asarray(prior, dtype=float).copy()
    n = len(chain.latest)
    labels = list(origins) if origins is not None else [str(i) for i in range(n)]
    if not np.isfinite(u0).any():
        return Skipped("MT13", "no prior ultimate available")

    p = 1 / chain.cdf_at_latest
    q = 1 - p
    latest = chain.latest
    bf = latest + q * u0
    estimate = u0.copy()
    for _ in range(iterations + 1):
        estimate = latest + q * estimate
    weight = 1 - q**iterations
    capped = (p > 1) & (weight > 1)  # closed form with weight 1 is the chain ladder
    weight = np.where(capped, 1.0, weight)
    ultimate = np.where(capped, chain.ultimate, estimate)

    not_run = {int(i): "no prior ultimate available" for i in np.flatnonzero(~np.isfinite(u0))}
    ultimate[list(not_run)] = np.nan
    diagnostics = [
        Diagnostic(
            "MT13",
            "WEIGHT_CAPPED",
            WARNING,
            f"origin {labels[i]}: cumulative development factor {chain.cdf_at_latest[i]:.4g} "
            "is below 1 (reported share above 1); the weight on the chain ladder is capped at 1",
            labels[i],
            float(p[i]),
        )
        for i in np.flatnonzero(p > 1)
    ]
    return Benktander(
        iterations=iterations,
        prior=Prior(prior_source),
        reported_share=p,
        unreported_share=q,
        prior_ultimate=u0,
        latest=latest,
        chain_ladder_ultimate=chain.ultimate,
        bornhuetter_ferguson_ultimate=bf,
        ultimate=ultimate,
        weight=weight,
        capped=capped,
        not_run=not_run,
        diagnostics=tuple(diagnostics),
    )
