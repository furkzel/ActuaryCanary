"""The true severity distribution of every line, for the extreme-value methods.

A regular claim's cost at base-date prices, in the reporting currency, is drawn as follows (see
``claims.py``): with probability ``tail.probability`` a Pareto draw (``threshold``, ``alpha``),
otherwise a draw from the body; then multiplied by ``litigation.severity_multiplier`` when the claim
is litigated. Catastrophe events, large events, caps at the sum insured and claims in a foreign
currency are not part of this distribution. The truth gives its parameters and its quantiles,
computed from the mixture, and the mean excess over a few thresholds.
"""

import numpy as np
import polars as pl
from scipy import integrate, optimize, stats

from actuarycanary.synthetic.scenario import Dist, Line, Scenario

LEVELS = (0.9, 0.95, 0.99, 0.995, 0.999)
EXCESS_LEVELS = (0.90, 0.95, 0.975, 0.99)


def _body_sf(body: Dist, x: np.ndarray) -> np.ndarray:
    if body.dist == "lognormal":
        assert body.median is not None and body.sigma is not None
        return stats.lognorm.sf(x, s=body.sigma, scale=body.median)
    if body.dist == "gamma":
        assert body.mean is not None and body.cv is not None
        shape = 1.0 / body.cv**2
        return stats.gamma.sf(x, a=shape, scale=body.mean / shape)
    raise ValueError(f"no distribution function for {body.dist}")


def _body_mean(body: Dist) -> float:
    if body.dist == "lognormal":
        assert body.median is not None and body.sigma is not None
        return float(body.median * np.exp(body.sigma**2 / 2))
    assert body.mean is not None
    return float(body.mean)


def _components(line: Line) -> list[tuple[float, float]]:
    """(weight, severity multiplier) of the litigation mixture."""
    lit = line.litigation
    if lit is None:
        return [(1.0, 1.0)]
    return [(1.0 - lit.probability, 1.0), (lit.probability, lit.severity_multiplier)]


def survival(line: Line, x: np.ndarray) -> np.ndarray:
    """Survival function of a regular claim's cost at base-date prices."""
    x = np.asarray(x, dtype=np.float64)
    out = np.zeros_like(x)
    tail = line.severity.tail
    for weight, multiplier in _components(line):
        y = x / multiplier
        body = _body_sf(line.severity.body, y)
        if tail is None:
            out += weight * body
            continue
        pareto = np.where(
            y >= tail.threshold, (tail.threshold / np.maximum(y, 1e-300)) ** tail.alpha, 1.0
        )
        out += weight * ((1.0 - tail.probability) * body + tail.probability * pareto)
    return out


def cdf(line: Line, x: np.ndarray) -> np.ndarray:
    """Distribution function of a regular claim's cost at base-date prices."""
    return 1.0 - survival(line, x)


def mean(line: Line) -> float:
    total = 0.0
    tail = line.severity.tail
    for weight, multiplier in _components(line):
        body = _body_mean(line.severity.body)
        if tail is None:
            total += weight * multiplier * body
        else:
            pareto = np.inf if tail.alpha <= 1 else tail.threshold * tail.alpha / (tail.alpha - 1)
            total += (
                weight * multiplier * ((1.0 - tail.probability) * body + tail.probability * pareto)
            )
    return float(total)


def quantile(line: Line, p: float) -> float:
    def gap(log_x: float) -> float:
        return float(cdf(line, np.array([np.exp(log_x)]))[0]) - p

    found = optimize.root_scalar(gap, bracket=[np.log(1e-3), np.log(1e12)], xtol=1e-12)
    return float(np.exp(found.root))


def _mean_excess(line: Line, u: float) -> float:
    """E[X - u | X > u]: the survival function integrated on a logarithmic scale up to a point far
    out, plus the Pareto tail beyond it (the tail index is the one of the scenario)."""
    far = 1e13

    def sf(x: float) -> float:
        return float(survival(line, np.array([x]))[0])

    area, _ = integrate.quad(
        lambda y: sf(float(np.exp(y))) * float(np.exp(y)),
        float(np.log(u)),
        float(np.log(far)),
        limit=400,
    )
    tail = line.severity.tail
    if tail is not None and tail.alpha > 1:
        area += sf(far) * far / (tail.alpha - 1.0)
    return area / sf(u)


def severity_truth(scenario: Scenario) -> dict[str, pl.DataFrame]:
    """`severity_truth` (one row per line) and `severity_tail_truth` (mean excess by level)."""
    rows: list[dict[str, object]] = []
    excess: list[dict[str, object]] = []
    for name, line in scenario.lines.items():
        if line.severity.body.dist not in ("lognormal", "gamma"):
            continue
        tail = line.severity.tail
        lit = line.litigation
        row: dict[str, object] = {
            "line": name,
            "body_dist": line.severity.body.dist,
            "body_median": line.severity.body.median,
            "body_sigma": line.severity.body.sigma,
            "body_mean": line.severity.body.mean,
            "body_cv": line.severity.body.cv,
            "tail_probability": None if tail is None else tail.probability,
            "tail_threshold": None if tail is None else tail.threshold,
            "tail_alpha": None if tail is None else tail.alpha,
            "tail_xi": None if tail is None else 1.0 / tail.alpha,
            "tail_gpd_sigma_at_threshold": None if tail is None else tail.threshold / tail.alpha,
            "tail_start_probability": None
            if tail is None
            else float(cdf(line, np.array([tail.threshold]))[0]),
            "litigation_probability": None if lit is None else lit.probability,
            "litigation_multiplier": None if lit is None else lit.severity_multiplier,
            "superimposed_inflation": line.severity.superimposed_inflation,
            "mean_severity": mean(line),
        }
        for p in LEVELS:
            row[f"quantile_{str(p).replace('.', '_')}"] = quantile(line, p)
        rows.append(row)
        for p in EXCESS_LEVELS:
            u = quantile(line, p)
            excess.append(
                {
                    "line": name,
                    "probability_level": p,
                    "threshold": u,
                    "mean_excess": _mean_excess(line, u),
                }
            )
    return {
        "severity_truth": pl.DataFrame(rows, infer_schema_length=None),
        "severity_tail_truth": pl.DataFrame(excess),
    }


MONEY_COLUMNS_SEVERITY = {
    "severity_truth": {
        **{
            c: ("reporting", "claim cost at base-date prices, reporting currency")
            for c in (
                "body_median",
                "body_mean",
                "tail_threshold",
                "tail_gpd_sigma_at_threshold",
                "mean_severity",
                *(f"quantile_{str(p).replace('.', '_')}" for p in LEVELS),
            )
        }
    },
    "severity_tail_truth": {
        "threshold": ("reporting", "claim cost at base-date prices, reporting currency"),
        "mean_excess": ("reporting", "claim cost at base-date prices, reporting currency"),
    },
}
