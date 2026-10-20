"""Random streams and distribution sampling. Every draw descends from one scenario seed."""

import hashlib

import numpy as np

from actuarycanary.synthetic.scenario import Dist


class Streams:
    """Named, independent random generators derived from one seed.

    A stream depends only on the seed and its name, so changing how many draws one stage
    makes never shifts the draws of another stage.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def get(self, *names: str) -> np.random.Generator:
        key = tuple(int.from_bytes(hashlib.sha256(n.encode()).digest()[:4], "big") for n in names)
        return np.random.default_rng(np.random.SeedSequence(self.seed, spawn_key=key))


def draw(spec: Dist, rng: np.random.Generator, n: int) -> np.ndarray:
    """`n` independent draws from `spec` (as floats)."""
    if spec.dist == "lognormal":
        assert spec.median is not None and spec.sigma is not None
        return spec.median * np.exp(spec.sigma * rng.standard_normal(n))
    if spec.dist == "gamma":
        assert spec.mean is not None and spec.cv is not None
        shape = 1.0 / spec.cv**2
        return rng.gamma(shape, spec.mean / shape, n)
    if spec.dist == "fixed":
        assert spec.value is not None
        return np.full(n, float(spec.value))
    if spec.dist == "poisson":
        assert spec.mean is not None
        counts = rng.poisson(spec.mean, n).astype(np.float64)
        return np.maximum(counts, spec.min) if spec.min is not None else counts
    raise ValueError(f"{spec.dist} cannot be drawn on its own")


def mean_of(spec: Dist) -> float:
    """Mean of a distribution, for expected values in the truth."""
    if spec.dist == "lognormal":
        assert spec.median is not None and spec.sigma is not None
        return float(spec.median * np.exp(spec.sigma**2 / 2))
    if spec.dist == "gamma":
        assert spec.mean is not None
        return spec.mean
    if spec.dist == "fixed":
        assert spec.value is not None
        return spec.value
    if spec.dist == "poisson":
        assert spec.mean is not None
        return spec.mean
    raise ValueError(f"{spec.dist} has no mean on its own")
