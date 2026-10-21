"""Presentation rounding (CV06): half away from zero on the shortest decimal representation."""

import math
from decimal import ROUND_HALF_UP, Decimal

AMOUNT_DECIMALS = 0
FACTOR_DECIMALS = 3
RATIO_DECIMALS = 1
COUNT_DECIMALS = 0
EMPTY = "–"


def round_half_away(value: float, decimals: int) -> Decimal:
    """round(x, d) per CV06; Decimal's ROUND_HALF_UP rounds ties away from zero."""
    return Decimal(repr(float(value))).quantize(
        Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP
    )


def _show(value: float | None, decimals: int, suffix: str = "") -> str:
    if value is None or not math.isfinite(value):
        return EMPTY
    rounded = round_half_away(value, decimals)
    if rounded == 0:
        rounded = abs(rounded)  # no "-0"
    return f"{rounded:,.{decimals}f}{suffix}"


def amount(value: float | None) -> str:
    return _show(value, AMOUNT_DECIMALS)


def factor(value: float | None) -> str:
    return _show(value, FACTOR_DECIMALS)


def ratio(value: float | None) -> str:
    return _show(None if value is None else value * 100, RATIO_DECIMALS, "%")


def count(value: float | None) -> str:
    return _show(value, COUNT_DECIMALS)
