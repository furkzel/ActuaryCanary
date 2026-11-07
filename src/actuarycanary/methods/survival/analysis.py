"""Survival analysis of claim settlement (MT19): Kaplan-Meier curves, percentiles of the time
to event, and a Cox proportional-hazards model.

The input is one row per claim: `claim_id`, `duration_days` (report to first closing, or to the
cut-off when the claim is still open), `event` (True when a closing was seen) and optionally
`segment`, `line`, `cause`, `size_class_at_report`, `size_class_at_cutoff`, `report_year` and
`approximate` (True where a date is a month end taken from a valuation). The analysis runs once
per segment. Kaplan-Meier curves are made for all claims of the segment, by line, by report year,
by every Cox covariate and, as a description only, by the size class at the cut-off, which depends
on the outcome. The Cox model uses the covariates of the parameter; a level with no events is
merged into the reference level, which is the level with the most events.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.diagnostics import WARNING, Diagnostic
from actuarycanary.methods.survival import cox as cox_module
from actuarycanary.methods.survival.cox import CoxFit, cox_fit
from actuarycanary.methods.survival.kaplan_meier import (
    KaplanMeier,
    kaplan_meier,
    log_rank,
    percentile_time,
)

METHOD = "MT19"
INFO = "INFO"
UNKNOWN = "UNKNOWN"
EVENT_CLOSED, EVENT_PAID = "closed", "closed_with_payment"
EVENTS = (EVENT_CLOSED, EVENT_PAID)
COVARIATE_CHOICES = ("line", "cause", "size_class_at_report")
COVARIATES = ("line",)
TIES = cox_module.TIES
TIES_DEFAULT = cox_module.EFRON
CONFIDENCE = 0.95
TIME_UNITS = {"days": 1.0, "months": 365.25 / 12.0, "years": 365.25}  # CV04: 365.25 days a year
TIME_UNIT = "days"
MIN_EVENTS = 20  # fewer events in a group: thin evidence, and no Cox model for the segment
PERCENTILES = (0.25, 0.5, 0.75)
SIGNIFICANCE = 0.01  # tests that flag a diagnostic
CURVE_ROWS = 400  # most rows of one curve in the output table (presentation only)
BASELINE_POINTS = 40  # times of a baseline curve in the output table
BASELINE_GROUPS = 30  # most covariate groups of the baseline table, the largest ones
RESIDUAL_POINTS = 300  # most scaled residuals of one covariate in the output table
BEYOND = "beyond observed range"
DESCRIPTIVE_GROUPING = (
    "size_class_at_cutoff (descriptive)"  # depends on the outcome: not a covariate
)
RUN, NOT_RUN = "fitted", "not run"


@dataclass(frozen=True)
class Survival:
    groups: pl.DataFrame  # segment, grouping, group: claims, events, censored share, thin evidence
    curves: pl.DataFrame  # Kaplan-Meier curve with interval, at most CURVE_ROWS rows per group
    percentiles: pl.DataFrame  # 25th, 50th and 75th percentile of time to event with interval
    models: pl.DataFrame  # segment: Cox status, reason, tests, concordance
    coefficients: pl.DataFrame  # segment, term: coefficient, hazard ratio, standard error, tests
    proportional_hazards: pl.DataFrame  # Grambsch-Therneau statistic per term and globally
    baseline: pl.DataFrame  # Breslow baseline survival per covariate group
    residuals: pl.DataFrame  # scaled Schoenfeld residuals against time
    cohorts: pl.DataFrame  # report years compared: share censored and the log-rank test
    diagnostics: tuple[Diagnostic, ...]
    options: dict[str, Any] = field(default_factory=dict)
    fits: dict[str, CoxFit] = field(default_factory=dict)  # by segment, for tests and callers

    @property
    def ran(self) -> bool:
        """Whether at least one curve or one model was made."""
        return self.groups.height > 0


GROUPS_SCHEMA = {
    "segment": pl.String,
    "grouping": pl.String,
    "group": pl.String,
    "claims": pl.Int64,
    "events": pl.Int64,
    "censored": pl.Int64,
    "share_censored": pl.Float64,
    "month_end_dates": pl.Int64,
    "status": pl.String,
    "descriptive": pl.Boolean,
}
CURVES_SCHEMA = {
    "segment": pl.String,
    "grouping": pl.String,
    "group": pl.String,
    "time": pl.Float64,
    "at_risk": pl.Int64,
    "events": pl.Int64,
    "censored": pl.Int64,
    "survival": pl.Float64,
    "standard_error": pl.Float64,
    "lower": pl.Float64,
    "upper": pl.Float64,
}
PERCENTILES_SCHEMA = {
    "segment": pl.String,
    "grouping": pl.String,
    "group": pl.String,
    "percentile": pl.Float64,
    "time": pl.Float64,
    "lower": pl.Float64,
    "upper": pl.Float64,
    "note": pl.String,
}
MODELS_SCHEMA = {
    "segment": pl.String,
    "status": pl.String,
    "reason": pl.String,
    "ties": pl.String,
    "covariates": pl.String,
    "claims": pl.Int64,
    "events": pl.Int64,
    "iterations": pl.Int64,
    "loglik_null": pl.Float64,
    "loglik": pl.Float64,
    "likelihood_ratio": pl.Float64,
    "likelihood_ratio_p": pl.Float64,
    "wald": pl.Float64,
    "wald_p": pl.Float64,
    "df": pl.Int64,
    "concordance": pl.Float64,
    "note": pl.String,
}
COEFFICIENTS_SCHEMA = {
    "segment": pl.String,
    "term": pl.String,
    "covariate": pl.String,
    "level": pl.String,
    "reference": pl.String,
    "claims": pl.Int64,
    "events": pl.Int64,
    "coefficient": pl.Float64,
    "hazard_ratio": pl.Float64,
    "standard_error": pl.Float64,
    "z": pl.Float64,
    "p_value": pl.Float64,
    "hazard_ratio_lower": pl.Float64,
    "hazard_ratio_upper": pl.Float64,
}
TEST_SCHEMA = {
    "segment": pl.String,
    "term": pl.String,
    "statistic": pl.Float64,
    "df": pl.Int64,
    "p_value": pl.Float64,
}
BASELINE_SCHEMA = {
    "segment": pl.String,
    "group": pl.String,
    "claims": pl.Int64,
    "time": pl.Float64,
    "cumulative_baseline_hazard": pl.Float64,
    "survival": pl.Float64,
}
RESIDUALS_SCHEMA = {
    "segment": pl.String,
    "term": pl.String,
    "time": pl.Float64,
    "transformed_time": pl.Float64,
    "scaled_residual": pl.Float64,
}
COHORTS_SCHEMA = {
    "segment": pl.String,
    "report_year": pl.String,
    "claims": pl.Int64,
    "events": pl.Int64,
    "share_censored": pl.Float64,
    "logrank_statistic": pl.Float64,
    "logrank_df": pl.Int64,
    "logrank_p": pl.Float64,
}


def _number(value: Any) -> float | None:
    return None if value is None or not math.isfinite(value) else float(value)


def _every(count: int, limit: int) -> np.ndarray:
    """Evenly spread positions, at most `limit`, always including the first and the last."""
    if count <= limit:
        return np.arange(count)
    return np.unique(np.linspace(0, count - 1, limit).round().astype(np.int64))


def _normalised(frame: pl.DataFrame) -> pl.DataFrame:
    for needed in ("claim_id", "duration_days", "event"):
        if needed not in frame.columns:
            raise ValueError(f"survival input needs a column {needed!r}")
    rows = frame
    for name in ("segment", "line", "cause", "size_class_at_report", "size_class_at_cutoff"):
        rows = (
            rows.with_columns(pl.col(name).cast(pl.String).fill_null(UNKNOWN))
            if name in rows.columns
            else rows.with_columns(pl.lit(UNKNOWN).alias(name))
        )
    rows = (
        rows.with_columns(pl.col("report_year").cast(pl.String).fill_null(UNKNOWN))
        if "report_year" in rows.columns
        else rows.with_columns(pl.lit(UNKNOWN).alias("report_year"))
    )
    if "approximate" not in rows.columns:
        rows = rows.with_columns(pl.lit(False).alias("approximate"))
    return rows.filter(pl.col("duration_days").is_not_null() & (pl.col("duration_days") >= 0)).sort(
        "claim_id"
    )


class _Rows:
    """Rows of the output tables of one analysis, built up group by group."""

    def __init__(self) -> None:
        self.groups: list[dict[str, Any]] = []
        self.curves: list[dict[str, Any]] = []
        self.percentiles: list[dict[str, Any]] = []
        self.models: list[dict[str, Any]] = []
        self.coefficients: list[dict[str, Any]] = []
        self.tests: list[dict[str, Any]] = []
        self.baseline: list[dict[str, Any]] = []
        self.residuals: list[dict[str, Any]] = []
        self.cohorts: list[dict[str, Any]] = []
        self.diagnostics: list[Diagnostic] = []
        self.fits: dict[str, CoxFit] = {}


def _frame(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema, infer_schema_length=None)


def survival_analysis(
    frame: pl.DataFrame,
    *,
    covariates: Sequence[str] = COVARIATES,
    ties: str = TIES_DEFAULT,
    confidence: float = CONFIDENCE,
    time_unit: str = TIME_UNIT,
    event: str = EVENT_CLOSED,
) -> Survival:
    """Kaplan-Meier curves and the Cox model of every segment of `frame`. `event` is only
    recorded: the caller decides what counts as the event when it builds the durations."""
    unknown = [c for c in covariates if c not in COVARIATE_CHOICES]
    if unknown:
        raise ValueError(f"covariates {unknown}: allowed {', '.join(COVARIATE_CHOICES)}")
    if ties not in TIES:
        raise ValueError(f"ties {ties!r}: allowed {', '.join(TIES)}")
    if time_unit not in TIME_UNITS:
        raise ValueError(f"time_unit {time_unit!r}: allowed {', '.join(TIME_UNITS)}")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie between 0 and 1")
    rows = _normalised(frame)
    out = _Rows()
    covariates = tuple(dict.fromkeys(covariates))
    for (segment,), part in rows.group_by(["segment"], maintain_order=True):
        _segment(str(segment), part, covariates, ties, confidence, time_unit, out)
    return Survival(
        groups=_frame(sorted(out.groups, key=_order), GROUPS_SCHEMA),
        curves=_frame(out.curves, CURVES_SCHEMA),
        percentiles=_frame(out.percentiles, PERCENTILES_SCHEMA),
        models=_frame(sorted(out.models, key=lambda r: r["segment"]), MODELS_SCHEMA),
        coefficients=_frame(out.coefficients, COEFFICIENTS_SCHEMA),
        proportional_hazards=_frame(out.tests, TEST_SCHEMA),
        baseline=_frame(out.baseline, BASELINE_SCHEMA),
        residuals=_frame(out.residuals, RESIDUALS_SCHEMA),
        cohorts=_frame(sorted(out.cohorts, key=_order), COHORTS_SCHEMA),
        diagnostics=tuple(out.diagnostics),
        options={
            "event": event,
            "covariates": list(covariates),
            "ties": ties,
            "confidence": confidence,
            "time_unit": time_unit,
        },
        fits=out.fits,
    )


def _order(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(k, "")) for k in ("segment", "grouping", "group", "report_year"))


def _segment(
    segment: str,
    part: pl.DataFrame,
    covariates: tuple[str, ...],
    ties: str,
    confidence: float,
    unit: str,
    out: _Rows,
) -> None:
    scale = TIME_UNITS[unit]
    time = part["duration_days"].to_numpy().astype(np.float64) / scale
    event = part["event"].to_numpy().astype(bool)
    approximate = part["approximate"].to_numpy().astype(bool)
    groupings: list[tuple[str, str, bool]] = [("all", "", False), ("line", "line", False)]
    groupings.append(("report_year", "report_year", False))
    groupings += [(c, c, False) for c in covariates if c != "line"]
    groupings.append((DESCRIPTIVE_GROUPING, "size_class_at_cutoff", True))
    for grouping, column, descriptive in groupings:
        labels = np.full(len(time), "all") if not column else part[column].to_numpy().astype(str)
        levels = sorted(set(labels))
        if column and levels == [UNKNOWN]:
            continue  # nothing to compare: the attribute is not known for any claim
        for level in levels:
            mask = labels == level
            _curve(segment, grouping, level, descriptive, time[mask], event[mask],
                   int(approximate[mask].sum()), confidence, out)  # fmt: skip
    _cohorts(segment, part, time, event, out)
    _cox(segment, part, time, event, covariates, ties, confidence, out)


def _curve(
    segment: str,
    grouping: str,
    group: str,
    descriptive: bool,
    time: np.ndarray,
    event: np.ndarray,
    approximate: int,
    confidence: float,
    out: _Rows,
) -> None:
    curve = kaplan_meier(time, event, confidence)
    thin = curve.n_events < MIN_EVENTS
    out.groups.append(
        {
            "segment": segment,
            "grouping": grouping,
            "group": group,
            "claims": curve.n,
            "events": curve.n_events,
            "censored": curve.n - curve.n_events,
            "share_censored": _number(curve.share_censored),
            "month_end_dates": approximate,
            "status": "thin evidence" if thin else "ok",
            "descriptive": descriptive,
        }
    )
    if thin:
        label = f"{segment} / {grouping} {group}" if grouping != "all" else segment
        out.diagnostics.append(
            Diagnostic(
                METHOD,
                "THIN_EVIDENCE",
                WARNING,
                f"{label}: only {curve.n_events} closings in {curve.n} claims (fewer than "
                f"{MIN_EVENTS}): the curve and its percentiles are shown but rest on few events",
                label,
                float(curve.n_events),
            )
        )
    for index in _every(len(curve.time), CURVE_ROWS):
        out.curves.append(
            {
                "segment": segment,
                "grouping": grouping,
                "group": group,
                "time": float(curve.time[index]),
                "at_risk": int(curve.at_risk[index]),
                "events": int(curve.events[index]),
                "censored": int(curve.censored[index]),
                "survival": float(curve.survival[index]),
                "standard_error": _number(curve.standard_error[index]),
                "lower": _number(curve.lower[index]),
                "upper": _number(curve.upper[index]),
            }
        )
    _percentiles(segment, grouping, group, curve, out)


def _percentiles(segment: str, grouping: str, group: str, curve: KaplanMeier, out: _Rows) -> None:
    for p in PERCENTILES:
        found, low, high = percentile_time(curve, p) if curve.n_events else (math.nan,) * 3
        note = "" if math.isfinite(found) else BEYOND
        if math.isfinite(found) and not (math.isfinite(low) and math.isfinite(high)):
            note = f"interval limit {BEYOND}"
        out.percentiles.append(
            {
                "segment": segment,
                "grouping": grouping,
                "group": group,
                "percentile": p,
                "time": _number(found),
                "lower": _number(low),
                "upper": _number(high),
                "note": note,
            }
        )


def _cohorts(
    segment: str, part: pl.DataFrame, time: np.ndarray, event: np.ndarray, out: _Rows
) -> None:
    """Report years side by side (assumptions: censoring independent of the time to close,
    cohorts comparable): the share censored per year and the log-rank test of equal hazards."""
    years = part["report_year"].to_numpy().astype(str)
    levels = sorted(set(years))
    if levels == [UNKNOWN]:
        return
    with_events = [y for y in levels if event[years == y].any()]
    test = None
    if len(with_events) >= 2:
        keep = np.isin(years, with_events)
        test = log_rank(time[keep], event[keep], years[keep])
    for year in levels:
        mask = years == year
        row = {
            "segment": segment,
            "report_year": year,
            "claims": int(mask.sum()),
            "events": int(event[mask].sum()),
            "share_censored": float(1.0 - event[mask].mean()),
            "logrank_statistic": None,
            "logrank_df": None,
            "logrank_p": None,
        }
        if test is not None and year == levels[0]:
            row["logrank_statistic"] = _number(test.statistic)
            row["logrank_df"] = test.df
            row["logrank_p"] = _number(test.p_value)
        out.cohorts.append(row)
    if test is not None and math.isfinite(test.p_value) and test.p_value < SIGNIFICANCE:
        out.diagnostics.append(
            Diagnostic(
                METHOD,
                "COHORTS_DIFFER",
                WARNING,
                f"{segment}: the time to closing differs between report years (log-rank test "
                f"p = {test.p_value:.2g}); the cohorts are not comparable, and a Cox model that "
                "pools them assumes one handling speed",
                segment,
                test.p_value,
            )
        )


@dataclass
class _Design:
    names: list[str]
    x: np.ndarray
    terms: list[dict[str, Any]]
    pattern: np.ndarray  # per claim: the covariate levels as one label
    notes: list[str]


def _design(part: pl.DataFrame, event: np.ndarray, covariates: tuple[str, ...]) -> _Design:
    columns: list[np.ndarray] = []
    names: list[str] = []
    terms: list[dict[str, Any]] = []
    notes: list[str] = []
    labels: list[list[str]] = []
    for covariate in covariates:
        values = part[covariate].to_numpy().astype(str)
        levels = sorted(set(values))
        if len(levels) == 1:
            notes.append(f"{covariate}: one level ({levels[0]}) in this segment, not used")
            continue
        events = {lvl: int(event[values == lvl].sum()) for lvl in levels}
        size = {lvl: int((values == lvl).sum()) for lvl in levels}
        reference = max(levels, key=lambda lvl: (events[lvl], size[lvl], lvl))
        for lvl in levels:
            if lvl != reference and events[lvl] == 0:
                notes.append(
                    f"{covariate}: level {lvl} has no events and is merged into the "
                    f"reference level {reference}"
                )
                values = np.where(values == lvl, reference, values)
        levels = sorted(set(values))
        if len(levels) == 1:
            notes.append(f"{covariate}: one level ({reference}) after merging, not used")
            continue
        notes.append(f"{covariate}: reference level {reference} (most events)")
        labels.append([f"{covariate}={v}" for v in values])
        for lvl in levels:
            if lvl == reference:
                continue
            mask = values == lvl
            columns.append(mask.astype(np.float64))
            names.append(f"{covariate}={lvl}")
            terms.append(
                {
                    "covariate": covariate,
                    "level": lvl,
                    "reference": reference,
                    "claims": int(mask.sum()),
                    "events": int(event[mask].sum()),
                }
            )
    x = np.column_stack(columns) if columns else np.empty((part.height, 0))
    pattern = np.array(
        [", ".join(parts) for parts in zip(*labels, strict=True)] or [""] * part.height
    )
    return _Design(names, x, terms, pattern, notes)


def _model_row(segment: str, status: str, reason: str, **given: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(MODELS_SCHEMA)
    row.update(segment=segment, status=status, reason=reason, note="")
    row.update(given)
    return row


def _cox(
    segment: str,
    part: pl.DataFrame,
    time: np.ndarray,
    event: np.ndarray,
    covariates: tuple[str, ...],
    ties: str,
    confidence: float,
    out: _Rows,
) -> None:
    n_events = int(event.sum())
    base = {
        "ties": ties,
        "covariates": ", ".join(covariates),
        "claims": len(time),
        "events": n_events,
    }

    def refuse(reason: str, note: str = "") -> None:
        out.models.append(_model_row(segment, NOT_RUN, reason, note=note, **base))
        out.diagnostics.append(
            Diagnostic(
                METHOD, "NO_COX_MODEL", WARNING, f"{segment}: no Cox model: {reason}", segment
            )
        )

    if n_events < MIN_EVENTS:
        refuse(f"fewer than {MIN_EVENTS} events ({n_events}) in {segment}")
        return
    design = _design(part, event, covariates)
    note = "; ".join(design.notes)
    if not design.names:
        refuse("no covariate varies between the claims of the segment", note)
        return
    fit = cox_fit(time, event, design.x, tuple(design.names), ties=ties, confidence=confidence)
    if isinstance(fit, Skipped):
        refuse(fit.reason, note)
        return
    out.fits[segment] = fit
    out.models.append(
        _model_row(
            segment, RUN, "", **base, iterations=fit.iterations,
            loglik_null=_number(fit.loglik_null), loglik=_number(fit.loglik),
            likelihood_ratio=_number(fit.likelihood_ratio),
            likelihood_ratio_p=_number(fit.likelihood_ratio_p), wald=_number(fit.wald),
            wald_p=_number(fit.wald_p), df=fit.df, concordance=_number(fit.concordance),
            note=note,
        )
    )  # fmt: skip
    for i, term in enumerate(design.terms):
        out.coefficients.append(
            {
                "segment": segment,
                "term": design.names[i],
                **term,
                "coefficient": _number(fit.coefficient[i]),
                "hazard_ratio": _number(fit.hazard_ratio[i]),
                "standard_error": _number(fit.standard_error[i]),
                "z": _number(fit.z[i]),
                "p_value": _number(fit.p_value[i]),
                "hazard_ratio_lower": _number(fit.hazard_ratio_lower[i]),
                "hazard_ratio_upper": _number(fit.hazard_ratio_upper[i]),
            }
        )
    _checks(segment, fit, design, out)


def _checks(segment: str, fit: CoxFit, design: _Design, out: _Rows) -> None:
    """The proportional-hazards test, its residuals and the baseline curves of a fitted model."""
    test = cox_module.proportional_hazards_test(fit)
    for i, name in enumerate(fit.names):
        out.tests.append(
            {
                "segment": segment,
                "term": name,
                "statistic": _number(test.statistic[i]),
                "df": 1,
                "p_value": _number(test.p_value[i]),
            }
        )
    out.tests.append(
        {
            "segment": segment,
            "term": "GLOBAL",
            "statistic": _number(test.global_statistic),
            "df": test.global_df,
            "p_value": _number(test.global_p_value),
        }
    )
    if math.isfinite(test.global_p_value) and test.global_p_value < SIGNIFICANCE:
        out.diagnostics.append(
            Diagnostic(
                METHOD,
                "NON_PROPORTIONAL_HAZARDS",
                WARNING,
                f"{segment}: the proportional-hazards test rejects (global p = "
                f"{test.global_p_value:.2g}); hazard ratios are averages over time",
                segment,
                test.global_p_value,
            )
        )
    keep = _every(len(test.time), RESIDUAL_POINTS)
    for i, name in enumerate(fit.names):
        for k in keep:
            out.residuals.append(
                {
                    "segment": segment,
                    "term": name,
                    "time": float(test.event_time[k]),
                    "transformed_time": float(test.time[k]),
                    "scaled_residual": _number(test.scaled_residuals[k, i]),
                }
            )
    times, hazard = cox_module.baseline_hazard(fit)
    patterns, first, counts = np.unique(design.pattern, return_index=True, return_counts=True)
    chosen = np.argsort(-counts, kind="stable")[:BASELINE_GROUPS]
    for g in sorted(chosen, key=lambda g: patterns[g]):
        multiplier = math.exp(float(design.x[first[g]] @ fit.coefficient))
        for k in _every(len(times), BASELINE_POINTS):
            out.baseline.append(
                {
                    "segment": segment,
                    "group": str(patterns[g]),
                    "claims": int(counts[g]),
                    "time": float(times[k]),
                    "cumulative_baseline_hazard": float(hazard[k]),
                    "survival": math.exp(-float(hazard[k]) * multiplier),
                }
            )
