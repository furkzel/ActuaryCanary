"""The `large_loss` section of project.yaml (CV08 1.1.0, record 0601).

`large_loss.percentile` replaces the default 99th percentile that sets the large-loss threshold of
each segment and line; `large_loss.thresholds` maps a "SEGMENT/LINE" key to a fixed amount at
value-date prices in reporting currency, which replaces the percentile for that group. The values
in force go to the run manifest.

The settings are read here and handed on as the two fields of the measure inputs
(`large_loss_percentile`, `large_loss_thresholds`); CV08 and M06 use them as they use the
defaults. The extreme-value threshold of MT18 never takes their place.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PERCENTILE = 0.99
KEYS = ("percentile", "thresholds")


class LargeLossError(ValueError):
    """The large_loss section is malformed."""


@dataclass(frozen=True)
class LargeLossSettings:
    percentile: float = DEFAULT_PERCENTILE
    thresholds: Mapping[tuple[str, str], float] = field(default_factory=dict)
    source: str = "default"  # "default" or "project.yaml"

    def manifest_record(self) -> dict[str, Any]:
        """The values in force, as the run manifest records them."""
        return {
            "percentile": self.percentile,
            "thresholds": {f"{s}/{line}": v for (s, line), v in sorted(self.thresholds.items())},
            "source": self.source,
        }


def parse_large_loss(section: object) -> LargeLossSettings:
    """Settings from the parsed `large_loss` mapping of project.yaml (None or empty: defaults)."""
    if section is None or section == {}:
        return LargeLossSettings()
    if not isinstance(section, Mapping):
        raise LargeLossError("large_loss must be a mapping with percentile and/or thresholds")
    unknown = sorted(str(k) for k in section if k not in KEYS)
    if unknown:
        raise LargeLossError(
            f"large_loss: unknown key {', '.join(unknown)}; allowed: {', '.join(KEYS)}"
        )
    percentile = DEFAULT_PERCENTILE
    if "percentile" in section:
        value = section["percentile"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LargeLossError(f"large_loss.percentile {value!r} is not a number")
        if not 0.0 < float(value) < 1.0:
            raise LargeLossError(f"large_loss.percentile {value} must lie between 0 and 1")
        percentile = float(value)
    thresholds: dict[tuple[str, str], float] = {}
    given = section.get("thresholds") or {}
    if not isinstance(given, Mapping):
        raise LargeLossError("large_loss.thresholds must map SEGMENT/LINE to an amount")
    for key, amount in given.items():
        segment, separator, line = str(key).partition("/")
        if not separator or not segment.strip() or not line.strip():
            raise LargeLossError(f"large_loss.thresholds key {key!r} must read SEGMENT/LINE")
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            raise LargeLossError(f"large_loss.thresholds {key}: {amount!r} is not a number")
        if not math.isfinite(float(amount)) or float(amount) <= 0:
            raise LargeLossError(f"large_loss.thresholds {key}: {amount!r} must be above zero")
        thresholds[(segment.strip(), line.strip())] = float(amount)
    return LargeLossSettings(percentile, thresholds, "project.yaml")
