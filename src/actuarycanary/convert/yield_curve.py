"""Yield curves for discounting (CV10, the data concept interest_rates).

A curve is one curve_id on one date. Every point becomes a continuously compounded zero rate
z(t) with t the tenor in years; the curve then stores the negative log discount factor
L(t) = z(t) t at its tenors and interpolates it linearly, which is a constant forward rate
between two tenors and keeps every discount factor positive. Before the first tenor z is flat
at the first point (L runs from the origin); beyond the last tenor the last forward rate is held
flat.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.canonical.feeds import Finding
from actuarycanary.io.excel import SOURCE_ROW

DAYS_PER_YEAR = 365.25
MONTHS_PER_YEAR = 12
ANNUAL, CONTINUOUS, SIMPLE = "ANNUAL", "CONTINUOUS", "SIMPLE"
SPOT, PAR, FORWARD = "SPOT", "PAR", "FORWARD"
RULE = "CV10"
FORWARD_FLOOR = -0.05  # DV-IRT-09
FORWARD_JUMP = 0.10  # DV-IRT-09


class CurveUnavailableError(Exception):
    """The curve cannot be used for discounting; the message is the reason (CV10)."""


@dataclass(frozen=True)
class YieldCurve:
    curve_id: str
    curve_date: date
    currency: str
    rate_type: str
    compounding: str
    source: str
    tenors: np.ndarray  # years, increasing, first above zero
    log_discount: np.ndarray  # L(t) = z(t) t at the tenors

    def _nodes(self) -> tuple[np.ndarray, np.ndarray]:
        return np.concatenate(([0.0], self.tenors)), np.concatenate(([0.0], self.log_discount))

    @property
    def last_forward(self) -> float:
        """The continuously compounded forward rate beyond the last tenor."""
        x, y = self._nodes()
        return float((y[-1] - y[-2]) / (x[-1] - x[-2]))

    def minus_log_discount(self, years: np.ndarray) -> np.ndarray:
        """L(t) for t in years; zero at and before today."""
        t = np.maximum(np.asarray(years, dtype=float), 0.0)
        x, y = self._nodes()
        inside = np.interp(t, x, y)
        beyond = y[-1] + self.last_forward * (t - x[-1])
        return np.where(t > x[-1], beyond, inside)

    def discount_factors(self, years: np.ndarray) -> np.ndarray:
        return np.exp(-self.minus_log_discount(years))

    def zero_rates(self, years: np.ndarray) -> np.ndarray:
        """z(t) = L(t) / t, the limit z(t1) at zero."""
        t = np.asarray(years, dtype=float)
        safe = np.where(t > 0, t, self.tenors[0])
        return self.minus_log_discount(safe) / safe

    def input_rates(self) -> np.ndarray:
        """The rate of each point in the terms the curve was given in (A1a, record 0751):
        SPOT in its own compounding, PAR as the par rate with annual coupons, FORWARD as the
        annually compounded one-year forward rate. For PAR and FORWARD the whole-year points
        between the given ones are the interpolated ones."""
        d = np.exp(-self.log_discount)
        if self.rate_type == PAR:
            return (1.0 - d) / np.cumsum(d)
        if self.rate_type != SPOT:
            return np.asarray(self.table()["forward_rate"].to_numpy())
        z = self.log_discount / self.tenors
        if self.compounding == CONTINUOUS:
            return z
        if self.compounding == SIMPLE:
            return np.expm1(self.log_discount) / self.tenors
        return np.expm1(z)

    def table(self) -> pl.DataFrame:
        """The points of the curve: tenor in years, the continuously compounded zero rate, the
        discount factor D(t) = exp(-z t) and the annually compounded forward rate from the
        previous point (see `input_rates` for the rate as it was given)."""
        previous = np.concatenate(([0.0], self.log_discount[:-1]))
        gap = np.diff(np.concatenate(([0.0], self.tenors)))
        forward = np.expm1((self.log_discount - previous) / gap)
        return pl.DataFrame(
            {
                "curve_id": [self.curve_id] * len(self.tenors),
                "curve_date": [self.curve_date] * len(self.tenors),
                "tenor_years": self.tenors,
                "zero_rate": self.log_discount / self.tenors,
                "discount_factor": np.exp(-self.log_discount),
                "forward_rate": forward,
            }
        )


def years_between(start: date, end: date) -> float:
    """Time in years from `start` to `end`: days divided by 365.25 (CV10)."""
    return (end - start).days / DAYS_PER_YEAR


def zero_rate(rate: float, tenor_years: float, compounding: str) -> float | None:
    """z(t) of a SPOT point; None for a SIMPLE point with 1 + r t not above zero."""
    if compounding == CONTINUOUS:
        return rate
    if compounding == SIMPLE:
        growth = 1.0 + rate * tenor_years
        return None if growth <= 0 else float(np.log(growth) / tenor_years)
    return float(np.log1p(rate))  # ANNUAL, and the default of an empty cell


def _whole_years(points: dict[int, float]) -> tuple[np.ndarray, np.ndarray]:
    """The given whole-year points, then every whole year from 1 to the last given tenor with
    the missing years interpolated linearly (flat before the first)."""
    given = np.array(sorted(points), dtype=float)
    values = np.array([points[int(n)] for n in given])
    years = np.arange(1, int(given[-1]) + 1, dtype=float)
    return years, np.interp(years, given, values)


def _par_nodes(points: dict[int, float]) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap of par rates with annual coupons (CV10): D(n) = (1 - c sum D(m)) / (1 + c)."""
    years, coupons = _whole_years(points)
    factors: list[float] = []
    for n, c in zip(years, coupons, strict=True):
        factor = (1.0 - c * sum(factors)) / (1.0 + c)
        if factor <= 0:
            raise CurveUnavailableError(
                f"the par bootstrap gives a discount factor at or below zero at the {int(n)}-year "
                "tenor (CV10)"
            )
        factors.append(factor)
    return years, -np.log(np.array(factors))


def _forward_nodes(points: dict[int, float]) -> tuple[np.ndarray, np.ndarray]:
    """One-year forwards accumulated from the first year (CV10)."""
    years, forwards = _whole_years(points)
    return years, np.cumsum(np.log1p(forwards))


def build_curve(
    rows: pl.DataFrame, curve_id: str, curve_date: date
) -> tuple[YieldCurve, list[Finding]]:
    """The curve of `curve_id` on `curve_date` from canonical rows of interest_rates (one
    rate type and compounding per curve and date, DV-IRT-07). Raises CurveUnavailableError."""
    part = rows.filter((pl.col("curve_id") == curve_id) & (pl.col("date") == curve_date))
    if part.height == 0:
        raise CurveUnavailableError(f"curve {curve_id} has no points on {curve_date}")
    rate_type = str(part["rate_type"][0])
    compounding = (
        str(part["compounding"][0])
        if "compounding" in part.columns and part["compounding"][0] is not None
        else ANNUAL
    )
    source = (
        str(part["source"][0]) if "source" in part.columns and part["source"][0] is not None else ""
    )
    currency = str(part["currency"][0])
    findings: list[Finding] = []
    tenors = part["tenor_months"].to_list()
    rates = part["rate"].to_list()
    if rate_type == SPOT:
        kept: list[tuple[float, float]] = []
        excluded: list[int] = []
        for position, (months, rate) in enumerate(zip(tenors, rates, strict=True)):
            t = months / MONTHS_PER_YEAR
            z = zero_rate(rate, t, compounding)
            if z is None:
                excluded.append(int(part[SOURCE_ROW][position]))
            else:
                kept.append((t, z * t))
        if excluded:
            findings.append(
                Finding(
                    "interest_rates",
                    RULE,
                    "WARNING",
                    len(excluded),
                    "simple-compounded points with 1 + r t at or below zero excluded",
                    tuple(excluded[:20]),
                )
            )
        if not kept:
            raise CurveUnavailableError(f"curve {curve_id} has no usable point on {curve_date}")
        ordered = sorted(kept)
        nodes_t = np.array([t for t, _ in ordered])
        nodes_l = np.array([v for _, v in ordered])
    else:
        by_year = {int(m) // MONTHS_PER_YEAR: float(r) for m, r in zip(tenors, rates, strict=True)}
        nodes_t, nodes_l = (_par_nodes if rate_type == PAR else _forward_nodes)(by_year)
    return (
        YieldCurve(
            curve_id, curve_date, currency, rate_type, compounding, source, nodes_t, nodes_l
        ),
        findings,
    )


def forward_findings(curve: YieldCurve) -> Finding | None:
    """DV-IRT-09: forwards below -0.05, or a change of more than 0.10 between adjacent
    tenors, listed as INFO."""
    table = curve.table()
    forward = table["forward_rate"].to_numpy()
    low = int((forward < FORWARD_FLOOR).sum())
    jumps = int((np.abs(np.diff(forward)) > FORWARD_JUMP).sum())
    if low + jumps == 0:
        return None
    return Finding(
        "interest_rates",
        "DV-IRT-09",
        "INFO",
        low + jumps,
        f"curve {curve.curve_id}: {low} forward rates below {FORWARD_FLOOR} and {jumps} changes "
        f"of more than {FORWARD_JUMP} between adjacent tenors",
    )


def curve_date_for(
    rows: pl.DataFrame, curve_id: str, discount_date: date
) -> tuple[date | None, str]:
    """The latest date of the curve on or before the discount date (CV10), or None with the
    reason."""
    own = rows.filter(pl.col("curve_id") == curve_id)
    if own.height == 0:
        return None, f"curve {curve_id} is not in the interest rates loaded"
    dates = own.filter(pl.col("date") <= discount_date)["date"]
    if dates.len() == 0:
        return None, (
            f"curve {curve_id} has no date on or before the discount date {discount_date} "
            "(DV-IRT-08)"
        )
    return dates.max(), ""  # type: ignore[return-value]
