"""Expected loss ratio method (MT05): ultimate as loss ratio times earned premium."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from actuarycanary.methods.bornhuetter_ferguson import (
    USER_PRIOR,
    premium_axis_reason,
    premium_reasons,
)
from actuarycanary.methods.chain_ladder import Skipped


@dataclass(frozen=True)
class ExpectedLossRatio:
    premium: np.ndarray
    loss_ratio: np.ndarray  # ELR(i)
    source: tuple[str, ...]  # per origin: user or data-derived prior
    ultimate: np.ndarray  # NaN for origins not run
    incurred: np.ndarray
    not_run: dict[int, str]

    @property
    def ibnr(self) -> np.ndarray:
        """U(i) minus incurred at the cut-off (RS02); may be negative."""
        return self.ultimate - self.incurred

    @property
    def negative_ibnr(self) -> np.ndarray:
        """Flag per origin (MT05 diagnostic)."""
        return np.nan_to_num(self.ibnr, nan=0.0) < 0


def expected_loss_ratio(
    premium: Sequence[float] | np.ndarray,
    loss_ratio: Sequence[float] | np.ndarray | float,
    incurred: Sequence[float] | np.ndarray,
    *,
    source: Sequence[str] | str = USER_PRIOR,
    origin_axis: str = "accident",
) -> ExpectedLossRatio | Skipped:
    """MT05 per origin; one loss ratio may be given for all origins."""
    reason = premium_axis_reason("the expected loss ratio method", origin_axis)
    if reason:
        return Skipped("MT05", reason)
    premium = np.asarray(premium, dtype=float)
    n = len(premium)
    ratio = np.broadcast_to(np.asarray(loss_ratio, dtype=float), (n,)).copy()
    if not np.isfinite(ratio).any():
        return Skipped("MT05", "no expected loss ratio available")
    not_run = premium_reasons(premium)
    for i in np.flatnonzero(~np.isfinite(ratio)):
        not_run.setdefault(int(i), "no expected loss ratio available")
    ultimate = ratio * premium
    ultimate[list(not_run)] = np.nan
    return ExpectedLossRatio(
        premium=premium,
        loss_ratio=ratio,
        source=(source,) * n if isinstance(source, str) else tuple(source),
        ultimate=ultimate,
        incurred=np.asarray(incurred, dtype=float),
        not_run=dict(sorted(not_run.items())),
    )
