"""Method registry: the tier B methods by specification ID, for the integration to call
(decision 0281).

Each entry names the function that implements the spec, the spec version it was built and
tested against, the inputs the caller must provide and whether it draws random numbers. The
registry calls nothing itself; the pipeline does not use it until the integration wires it.
`settings` and `randomness` give what a run must record in the manifest (and so in the run id)
when it runs these methods: the seed and the default parameters.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from actuarycanary.methods import (
    back_testing,
    benktander,
    frequency_severity,
    munich,
    odp_bootstrap,
    separation,
    tail,
)
from actuarycanary.methods.judgement_tier_b import PARAMETERS
from actuarycanary.methods.seeding import RUN_SEED


@dataclass(frozen=True)
class MethodEntry:
    id: str
    spec_version: str  # the version the implementation is tested against
    function: Callable[..., Any]
    inputs: str  # what the caller passes, in words
    random: str = ""  # what it draws from a seeded stream (`seeding.generator`), if anything
    measure: str = ""  # the triangle it runs on by default

    @property
    def qualified_name(self) -> str:
        return f"{self.function.__module__}.{self.function.__qualname__}"


ENTRIES: tuple[MethodEntry, ...] = (
    MethodEntry(
        "MT11", "1.0.0", odp_bootstrap.odp_bootstrap,
        "cumulative paid triangle; the group's stream seeding.generator(seed, *group)",
        random="residual resampling and process error, one stream per group", measure="paid",
    ),
    MethodEntry(
        "MT12", "1.0.0", munich.munich_chain_ladder,
        "cumulative paid and incurred triangles on the same grid", measure="paid+incurred",
    ),
    MethodEntry(
        "MT13", "1.0.0", benktander.benktander,
        "MT02 result and the MT03 or MT04 result (or the prior ultimate per origin)",
        measure="incurred",
    ),
    MethodEntry(
        "MT14", "1.0.0", tail.fit_tail,
        "MT02 selected factors and the ages of the triangle; selection through "
        "judgement_tier_b.chain_ladder_with_tail",
        measure="paid",
    ),
    MethodEntry(
        "MT15", "1.0.0", separation.separation,
        "incremental paid triangle (square) and claim counts per origin (MT16 ultimate counts)",
        measure="paid",
    ),
    MethodEntry(
        "MT16", "1.0.0", frequency_severity.frequency_severity,
        "non-nil reported count triangle and the severity-measure triangle without "
        "catastrophe claims, the catastrophe triangle, earned exposure per origin",
        measure="incurred",
    ),
    MethodEntry(
        "MT22", "1.0.0", back_testing.back_test,
        "cumulative triangle with its calendar, today's selected ultimate and maturity per "
        "origin; runners or past estimates (modules.reserving.earlier_result)",
        random="the optional MT11 rerun at past cut-offs, one stream per group",
        measure="incurred",
    ),
    MethodEntry(
        "AE02", "1.0.0", back_testing.ae02_errors,
        "past ultimates and today's reference per origin; weighted_errors for B, MAE, RMSE",
    ),
)  # fmt: skip

REGISTRY: dict[str, MethodEntry] = {e.id: e for e in ENTRIES}


def get(spec_id: str) -> MethodEntry:
    try:
        return REGISTRY[spec_id]
    except KeyError:
        raise KeyError(f"no tier B implementation registered for {spec_id}") from None


def settings(seed: int = RUN_SEED) -> dict[str, Any]:
    """The tier B part of the run settings: the seed and every default parameter, so that a
    change of either changes the run id once the integration records it."""
    return {
        "seed": seed,
        "methods": {
            method: {p.name: p.default for p in parameters}
            for method, parameters in sorted(PARAMETERS.items())
        },
    }


def randomness(seed: int = RUN_SEED) -> list[dict[str, Any]]:
    """Manifest rows for the random draws of the registered methods (as MT09's row)."""
    return [{"method": e.id, "seed": seed, "purpose": e.random} for e in ENTRIES if e.random]
