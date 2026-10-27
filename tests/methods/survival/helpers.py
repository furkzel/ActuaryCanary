"""Shared builders of the survival tests: duration frames, simulated Weibull data and the
frozen references."""

import csv
from pathlib import Path

import numpy as np
import polars as pl

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.survival.cox import CoxFit
from tests.benchmarks.load import load_reference, load_table

CLOSED, OPEN, NIL, REOPENED = "CLOSED", "OPEN", "CLOSED_NIL", "REOPENED"


def fitted(result: CoxFit | Skipped) -> CoxFit:
    """The fit, or a failed assertion that says why the model did not run."""
    assert isinstance(result, CoxFit), result
    return result


def reference(name: str):
    ref = load_reference(name)
    return ref["folder"], ref["values"]


def cox_data(folder: Path, covariates: list[str]):
    """(time, event, x) of a Cox reference folder."""
    with (folder / "data.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    time = np.array([float(r["time"]) for r in rows])
    event = np.array([int(r["event"]) == 1 for r in rows])
    x = np.array([[float(r[c]) for c in covariates] for r in rows])
    return time, event, x


def hand_times() -> tuple[np.ndarray, np.ndarray]:
    folder, _ = reference("MT19-kaplan-meier-ten-times")
    rows = load_table(folder / "times.csv")
    return (
        np.array([float(r["time"]) for r in rows]),
        np.array([int(r["event"]) == 1 for r in rows]),
    )


def durations_frame(
    time,
    event,
    *,
    segment: str = "S",
    line=None,
    cause=None,
    size_class=None,
    cutoff_class=None,
    year=None,
    approximate=None,
) -> pl.DataFrame:
    """One row per claim, in the columns `survival_analysis` takes (times are in days)."""
    n = len(time)
    return pl.DataFrame(
        {
            "claim_id": [f"C{i:06d}" for i in range(n)],
            "duration_days": np.asarray(time, dtype=float),
            "event": np.asarray(event, dtype=bool),
            "segment": [segment] * n,
            "line": list(line) if line is not None else ["L"] * n,
            "cause": list(cause) if cause is not None else ["X"] * n,
            "size_class_at_report": list(size_class) if size_class is not None else ["A"] * n,
            "size_class_at_cutoff": list(cutoff_class) if cutoff_class is not None else ["A"] * n,
            "report_year": list(year) if year is not None else [2024] * n,
            "approximate": list(approximate) if approximate is not None else [False] * n,
        }
    )


def weibull_sample(
    rng: np.random.Generator, n: int, beta: np.ndarray, shape: float = 1.5, censor_rate: float = 0.4
):
    """Weibull proportional-hazards times with independent exponential censoring:
    h(t | x) = shape * t^(shape - 1) * exp(beta'x), so T = (-ln U / exp(beta'x))^(1 / shape)."""
    p = len(beta)
    x = rng.binomial(1, 0.5, size=(n, p)).astype(float)
    t_event = (-np.log(rng.random(n)) / np.exp(x @ beta)) ** (1.0 / shape)
    t_censor = rng.exponential(1.0 / censor_rate, n)
    time = np.minimum(t_event, t_censor)
    return time, t_event <= t_censor, x
