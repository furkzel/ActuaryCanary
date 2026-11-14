"""Likely causes of a material gap (CV12, record 0424): four small tests, each on the data the
gap has, each returning a suggestion with its evidence or nothing.

They are suggestions, never findings of fact: the module labels them "suggested". A gap no test
supports says "no cause suggested". The thresholds are the constants below, with their reasons in
record 0424.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

CUT_OFF_TIMING = "CUT_OFF_TIMING"
CURRENCY = "CURRENCY"
IBNR_IN_OUTSTANDING = "IBNR_IN_OUTSTANDING"
UNMAPPED_ACCOUNT = "UNMAPPED_ACCOUNT"

OFFSET_TOLERANCE = 0.05  # the next month's gap offsets this one within 5 % of the larger
CURRENCY_BOUND = 0.05  # the gap is at most 5 % of the foreign-currency part of the figure
IBNR_MIN_MONTHS = 3  # a loading that stays the same in at least three months
IBNR_SPREAD = 0.10  # ... within 10 % of its mean (spread over mean)
UNMAPPED_TOLERANCE = 0.25  # the unmapped balance is within 25 % of the size of the gap


@dataclass(frozen=True)
class Cause:
    code: str
    evidence: str


def _month(day: date) -> int:
    return day.year * 12 + day.month - 1


def cut_off_timing(period: date, gaps: Mapping[date, float]) -> Cause | None:
    """The gap of a month is offset by the opposite gap of the month before or after it: an
    amount booked in the books in the wrong month (cut-off timing). `gaps` are the gaps of the
    same entity and class by month end."""
    gap = gaps.get(period)
    if not gap:
        return None
    by_month = {_month(d): g for d, g in gaps.items()}
    for step in (1, -1):
        neighbour = by_month.get(_month(period) + step)
        if neighbour is None or neighbour * gap >= 0:
            continue
        if abs(gap + neighbour) <= OFFSET_TOLERANCE * max(abs(gap), abs(neighbour)):
            where = f"{(_month(period) + step) // 12}-{(_month(period) + step) % 12 + 1:02d}"
            return Cause(
                CUT_OFF_TIMING,
                f"the gap of {gap:,.0f} is offset by {neighbour:,.0f} in {where}",
            )
    return None


def currency(gap: float, foreign: float | None) -> Cause | None:
    """The month's figure has foreign-currency rows and the gap is of the size of a rate
    difference on them (at most `CURRENCY_BOUND` of their amount)."""
    if not foreign or foreign <= 0 or abs(gap) > CURRENCY_BOUND * foreign:
        return None
    return Cause(
        CURRENCY,
        f"{foreign:,.0f} of the month's figure is in foreign currency and the gap is "
        f"{abs(gap) / foreign:.1%} of it, the size of a difference in the rate used",
    )


def ibnr_in_outstanding(
    account_class: str, period: date, loadings: Mapping[date, float]
) -> Cause | None:
    """The ledger outstanding is above the case reserve by about the same share in several
    months. `loadings` are (ledger - platform) / platform of the months in which the gap is
    material and the ledger is the larger."""
    if account_class != "OUTSTANDING" or period not in loadings:
        return None
    values = list(loadings.values())
    if len(values) < IBNR_MIN_MONTHS:
        return None
    mean = sum(values) / len(values)
    if mean <= 0 or (max(values) - min(values)) > IBNR_SPREAD * mean:
        return None
    first = min(loadings)
    return Cause(
        IBNR_IN_OUTSTANDING,
        f"the ledger outstanding is {mean:.1%} above the case reserve in {len(values)} months "
        f"(from {first:%Y-%m}), a loading that stays the same, as an IBNR provision would",
    )


def unmapped_account(gap: float, balance: float, accounts: Sequence[str]) -> Cause | None:
    """Accounts the profile does not map hold a balance about the size of the gap in the same
    month: the amount may be booked there."""
    if not balance or abs(abs(gap) - balance) > UNMAPPED_TOLERANCE * balance:
        return None
    return Cause(
        UNMAPPED_ACCOUNT,
        f"unmapped account {', '.join(accounts)} holds {balance:,.0f} in the month, "
        "about the size of the gap",
    )
