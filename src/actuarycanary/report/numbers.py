"""Presentation rounding (CV06): half away from zero on the shortest decimal representation.

Numbers are written with the separators of the report language: 1,234.5 and 12.3% in English,
1.234,5 and %12,3 in Turkish (record 0224). The rounding is the same in both.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

from actuarycanary.report import language

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


def _show(value: float | None, decimals: int) -> str:
    if value is None or not math.isfinite(value):
        return EMPTY
    rounded = round_half_away(value, decimals)
    if rounded == 0:
        rounded = abs(rounded)  # no "-0"
    return language.number_text(f"{rounded:,.{decimals}f}")


def amount(value: float | None) -> str:
    return _show(value, AMOUNT_DECIMALS)


def factor(value: float | None) -> str:
    return _show(value, FACTOR_DECIMALS)


def _percent(shown: str) -> str:
    """A number as a percentage: 12.3% in English, %12,3 in Turkish."""
    if shown == EMPTY:
        return shown
    if language.current() == language.TURKISH:
        return f"{'-' if shown.startswith('-') else ''}%{shown.lstrip('-')}"
    return f"{shown}%"


def ratio(value: float | None) -> str:
    return _percent(_show(None if value is None else value * 100, RATIO_DECIMALS))


def count(value: float | None) -> str:
    return _show(value, COUNT_DECIMALS)


def score(value: float | None) -> str:
    """A score out of 100 (DQ01), one decimal."""
    return _show(value, RATIO_DECIMALS)


def _signed(text: str) -> str:
    if text == EMPTY:
        return text
    if text.startswith("-"):
        return text.replace("-", "−", 1)
    return text if not any(digit in text for digit in "123456789") else f"+{text}"


def change_amount(value: float | None) -> str:
    """A change with its sign: +1,234 or −1,234."""
    return _signed(amount(value))


def change_ratio(value: float | None) -> str:
    """A relative change with its sign: +12.3% or −4.0%."""
    return _signed(ratio(value))


def change_points(value: float | None) -> str:
    """A change of a ratio in percentage points: +1.2 pts."""
    shown = _show(None if value is None else value * 100, RATIO_DECIMALS)
    return shown if shown == EMPTY else language.t("{change} pts", change=_signed(shown))
