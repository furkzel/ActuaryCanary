"""Tail factor fitting (MT14): a decay curve through the excess development of the selected factors.

The excess f(x) - 1 of the selected age-to-age factors (MT02) is fitted by ordinary least
squares on the log scale against the link number x = 1, 2, ... (exponential decay) or its
logarithm (inverse power), then extended one development period at a time for a fixed number of
periods. The product is the tail factor; the part of the product beyond those periods is reported
as the remainder (decisions 0608, 0614). The fitted tail replaces the MT02 tail factor only when
the user selects it in the assumptions register (`methods.judgement_tier_b`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.diagnostics import WARNING, Diagnostic

MIN_POINTS = 3
EXTENSION_PERIODS = 100  # decision 0608
REMAINDER_WARNING = 0.005  # decision 0614
REMAINDER_PERIODS = 1_000_000  # the remainder runs the product this far (MT14)
REMAINDER_INCREMENT = 1e-12  # or until the increment is below this


class Curve(StrEnum):
    EXPONENTIAL_DECAY = "exponential_decay"
    INVERSE_POWER = "inverse_power"


@dataclass(frozen=True)
class CurveFit:
    curve: Curve
    a: float
    b: float  # exponential: ln(f - 1) = a + b x; inverse power: ln(f - 1) = a - b ln x
    r_squared: float  # on the log scale
    columns: tuple[int, ...]  # fitted development columns
    link_numbers: np.ndarray  # x of the fitted columns
    tail_factor: float  # tau over the extension periods
    tail_remainder: float  # rho: the product beyond the extension periods over tau, minus 1
    extension_factors: np.ndarray  # 1 + e^a g(x) per period beyond the triangle
    extension_share: np.ndarray  # share of the ultimate (at tail tau) each period adds
    fitted_factors: np.ndarray  # 1 + e^a g(x) on every observed column

    def excess(self, x: np.ndarray) -> np.ndarray:
        return excess(self.curve, self.a, self.b, x)


@dataclass(frozen=True)
class TailFit:
    curve: Curve  # the chosen curve (parameter `curve`)
    fits: dict[Curve, CurveFit | Skipped]  # both curves, the other one for comparison
    selected_factors: np.ndarray
    diagnostics: tuple[Diagnostic, ...]

    @property
    def chosen(self) -> CurveFit | Skipped:
        return self.fits[self.curve]

    @property
    def tail_factor(self) -> float:
        """tau of the chosen curve; NaN when it could not be used."""
        chosen = self.chosen
        return chosen.tail_factor if isinstance(chosen, CurveFit) else float("nan")


def excess(curve: Curve, a: float, b: float, x: np.ndarray) -> np.ndarray:
    """e^a g(x): g(x) = e^(b x) for exponential decay, x^(-b) for inverse power."""
    x = np.asarray(x, dtype=float)
    if curve is Curve.EXPONENTIAL_DECAY:
        return np.exp(a + b * x)
    return np.exp(a) * x ** (-b)


def _remainder(curve: Curve, a: float, b: float, first: int, periods: int) -> float:
    """rho: the product over the periods after the extension, as far as 1e6 periods from the
    end of the triangle or until the increment is below 1e-12, minus 1 (equal to the product
    over every x >= first divided by tau, minus 1, without the cancellation)."""
    x = np.arange(first + periods, first + REMAINDER_PERIODS, dtype=float)
    increments = excess(curve, a, b, x)
    below = np.flatnonzero(increments < REMAINDER_INCREMENT)
    if len(below):
        increments = increments[: below[0]]
    return float(np.expm1(np.log1p(increments).sum()))


def _fit(
    curve: Curve,
    factors: np.ndarray,
    columns: list[int],
    extension_periods: int,
) -> CurveFit | Skipped:
    x = np.array([j + 1 for j in columns], dtype=float)  # link number (MT14, CV04)
    y = np.log(factors[columns] - 1)
    design = x if curve is Curve.EXPONENTIAL_DECAY else np.log(x)
    slope, intercept = np.polyfit(design, y, 1)
    a = float(intercept)
    b = float(slope) if curve is Curve.EXPONENTIAL_DECAY else -float(slope)
    if curve is Curve.EXPONENTIAL_DECAY and b >= 0:
        return Skipped("MT14", f"exponential decay slope b = {b:.4g} is not below 0")
    if curve is Curve.INVERSE_POWER and b <= 1:
        return Skipped(
            "MT14", f"inverse power slope b = {b:.4g} is not above 1, so the product diverges"
        )
    fitted_y = intercept + slope * design
    total = float(((y - y.mean()) ** 2).sum())
    r_squared = 1 - float(((y - fitted_y) ** 2).sum()) / total if total > 0 else 1.0

    first = len(factors) + 1  # link number after the last column of the triangle
    extension = 1 + excess(curve, a, b, np.arange(first, first + extension_periods))
    products = np.cumprod(extension)
    tau = float(products[-1]) if extension_periods else 1.0
    added = np.diff(np.concatenate([[1.0], products]))
    observed = np.arange(1, len(factors) + 1)
    return CurveFit(
        curve=curve,
        a=a,
        b=b,
        r_squared=r_squared,
        columns=tuple(columns),
        link_numbers=x,
        tail_factor=tau,
        tail_remainder=_remainder(curve, a, b, first, extension_periods),
        extension_factors=extension,
        extension_share=added / tau,
        fitted_factors=1 + excess(curve, a, b, observed),
    )


def fit_tail(
    factors: Sequence[float] | np.ndarray,
    ages: Sequence[int],
    *,
    curve: Curve = Curve.EXPONENTIAL_DECAY,
    fit_from_age: int | None = None,
    min_points: int = MIN_POINTS,
    extension_periods: int = EXTENSION_PERIODS,
    remainder_warning: float = REMAINDER_WARNING,
) -> TailFit | Skipped:
    """MT14 on the selected factors of MT02 (column j runs from ages[j] to ages[j + 1])."""
    factors = np.asarray(factors, dtype=float)
    if extension_periods < 0:
        raise ValueError(f"extension periods {extension_periods} must be at least 0")
    start = 0
    if fit_from_age is not None:
        later = [j for j in range(len(factors)) if ages[j] >= fit_from_age]
        if not later:
            return Skipped("MT14", f"no development column starts at or after {fit_from_age}")
        start = later[0]
    columns = [j for j in range(start, len(factors)) if factors[j] > 1]
    if len(columns) < min_points:
        return Skipped("MT14", "too few factors above 1 to fit a tail")
    fits = {c: _fit(c, factors, columns, extension_periods) for c in Curve}
    diagnostics: list[Diagnostic] = []
    for fit in fits.values():
        if isinstance(fit, Skipped):
            diagnostics.append(Diagnostic("MT14", "CURVE_NOT_USED", WARNING, fit.reason))
        elif fit.tail_remainder > remainder_warning:
            diagnostics.append(
                Diagnostic(
                    "MT14",
                    "DEVELOPMENT_NOT_STOPPED",
                    WARNING,
                    f"{fit.curve.value.replace('_', ' ')} tail {fit.tail_factor:.6g}: development "
                    f"had not stopped within {extension_periods} periods; the rest of the "
                    f"product adds {fit.tail_remainder:.2%} more",
                    fit.curve.value,
                    fit.tail_remainder,
                )
            )
    return TailFit(Curve(curve), fits, factors, tuple(diagnostics))


def ultimates_with_tail(chain: ChainLadder, tail_factor: float) -> np.ndarray:
    """The chain-ladder ultimates with `tail_factor` in place of the MT02 tail (diagnostic)."""
    return chain.ultimate / chain.tail_factor * tail_factor
