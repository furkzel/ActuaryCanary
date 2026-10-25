"""Shared builders of the severity tests: a frame of claim sizes and the frozen references."""

from collections.abc import Sequence
from functools import cache
from pathlib import Path

import numpy as np
import polars as pl

from tests.benchmarks.load import load_reference, load_table

CLOSED, OPEN, NIL = "CLOSED", "OPEN", "CLOSED_NIL"


def sizes_frame(
    sizes: Sequence[float] | np.ndarray,
    *,
    status: str | Sequence[str] = CLOSED,
    segment: str = "S",
    line: str = "L",
    years: Sequence[int] | np.ndarray | None = None,
    event_codes: Sequence[str | None] | None = None,
    prefix: str = "C",
) -> pl.DataFrame:
    """One row per claim: claim_id, size, status, segment, line, origin_year, event_code."""
    n = len(sizes)
    statuses = [status] * n if isinstance(status, str) else list(status)
    return pl.DataFrame(
        {
            "claim_id": [f"{prefix}{i:06d}" for i in range(n)],
            "size": np.asarray(sizes, dtype=float),
            "status": statuses,
            "segment": [segment] * n,
            "line": [line] * n,
            "origin_year": list(years) if years is not None else [None] * n,
            "event_code": list(event_codes) if event_codes is not None else [None] * n,
        },
        schema_overrides={"origin_year": pl.Int64, "event_code": pl.String},
    )


@cache
def severity_samples() -> dict[str, np.ndarray]:
    """The four 500-size samples frozen in tier_b/MT17-severity-fits (one per family)."""
    folder = load_reference("MT17-severity-fits")["folder"]
    rows = load_table(Path(folder) / "samples.csv")
    return {name: np.array([float(r[name]) for r in rows]) for name in rows[0] if name != "claim"}


@cache
def gpd_samples() -> dict[str, np.ndarray]:
    """The lognormal sample and the 400 generalised Pareto excesses frozen in tier_b/MT18."""
    folder = Path(load_reference("MT18-gpd-fits")["folder"])
    lognormal = load_table(folder / "sample_lognormal.csv")
    excess = load_table(folder / "sample_gpd_excesses.csv")
    return {
        "lognormal": np.array([float(r["size"]) for r in lognormal]),
        "excess": np.array([float(r["excess_over_100000"]) for r in excess]),
    }


def spliced_sizes(
    rng: np.random.Generator,
    n: int,
    tail_share: float = 0.1,
    xi: float = 0.3,
    scale: float = 2e4,
) -> tuple[np.ndarray, float]:
    """Sizes with a lognormal body (median 10,000, sigma 1) below a start u0 and a generalised
    Pareto tail (shape xi, scale `scale`) above it; P(X > u0) is `tail_share`. u0 is the
    lognormal quantile at 1 - tail_share, so the body is the lognormal cut at u0 and the density
    is continuous in probability. Returns the sizes and u0."""
    from scipy import stats

    u0 = float(stats.lognorm.ppf(1.0 - tail_share, 1.0, scale=1e4))
    in_tail = rng.random(n) < tail_share
    body = stats.lognorm.ppf(rng.random(n) * (1.0 - tail_share), 1.0, scale=1e4)
    tail = u0 + stats.genpareto.rvs(xi, scale=scale, size=n, random_state=rng)
    return np.where(in_tail, tail, body), u0


def spliced_quantile(p: float, u0: float, tail_share: float, xi: float, scale: float) -> float:
    """The true p-quantile of `spliced_sizes` above its start: P(X > x) = tail_share x
    (1 + xi (x - u0) / scale)^(-1 / xi)."""
    return u0 + scale / xi * (((1.0 - p) / tail_share) ** (-xi) - 1.0)
