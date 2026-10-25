"""Severity and extreme values: MT17 (severity distribution fitting) and MT18 (peaks over
threshold). Both take one frame of claim sizes, see `sizes.group_sizes`, and are seeded."""

from actuarycanary.methods.severity.evt import ExtremeValues, extreme_values, forward_stop
from actuarycanary.methods.severity.fitting import SeverityFits, compare_claim_sets, fit_severity
from actuarycanary.methods.severity.judgement import mt17_judged, mt18_judged
from actuarycanary.methods.severity.large_loss import (
    LargeLossError,
    LargeLossSettings,
    parse_large_loss,
)
from actuarycanary.methods.severity.sizes import SEED, group_sizes

__all__ = [
    "SEED",
    "ExtremeValues",
    "LargeLossError",
    "LargeLossSettings",
    "SeverityFits",
    "compare_claim_sets",
    "extreme_values",
    "fit_severity",
    "forward_stop",
    "group_sizes",
    "mt17_judged",
    "mt18_judged",
    "parse_large_loss",
]
