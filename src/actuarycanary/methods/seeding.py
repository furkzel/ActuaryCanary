"""Seeded random streams of the stochastic methods (blueprint 12, decision 0281).

Every random draw starts from the run seed. A method that runs once per group (segment, line,
measure) draws from its own stream, derived from the seed and the group's key, so that a group's
draws do not depend on which other groups ran or in which order. With no key the stream is
numpy's `default_rng(seed)`, which is what the benchmarks use.
"""

import hashlib

import numpy as np

RUN_SEED = 1  # the run seed until runs carry a seed setting of their own (decision 0281)


def key_words(*keys: str) -> tuple[int, ...]:
    """A stable spawn key: the SHA-256 of the keys as four 32-bit words."""
    digest = hashlib.sha256("\x1f".join(keys).encode("utf-8")).digest()
    return tuple(int.from_bytes(digest[k : k + 4], "little") for k in range(0, 16, 4))


def generator(seed: int, *keys: str) -> np.random.Generator:
    """The random stream of `seed` for one group; `default_rng(seed)` when no key is given."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed {seed!r} must be a whole number >= 0")
    if not keys:
        return np.random.default_rng(seed)
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=key_words(*keys)))
