"""MT19 on the claims of a run (records 0616, 0630).

Each claim's duration runs from its report date to its first closing, or to the cut-off when it
is still open (censored). The dates are the ones CL08 reads: the report and close dates of
`claims`, and, where `claims` is not loaded or has no date for a claim, the month-end valuation
dates of `claim_valuations` (the first valuation stands for the report, the first closed status
for the closing; labelled as month-end approximations). A claim that was reopened has its first
closing from the valuations, because the close date of `claims` is the last one. The size class
at report is CV08's class of the incurred at the first valuation; the class at the cut-off is
only a description.

The methods run once per segment, each with the register's entries for its scope
(`SEGMENT/survival`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import ConversionError
from actuarycanary.measures.claim_base import (
    amounts_at,
    header,
    left_out,
    size_classes,
    status_rows,
)
from actuarycanary.measures.claim_counts import CLOSED
from actuarycanary.measures.model import Basis, CurrencyView, MeasureInputs, MeasureRequest
from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.diagnostics import Diagnostic
from actuarycanary.methods.survival import analysis as an
from actuarycanary.methods.survival import mt19_judged, survival_analysis

MT19 = "MT19"
PAID_CLOSING = "CLOSED"
TABLES = {
    "groups": "survival_groups.csv",
    "curves": "survival_curves.csv",
    "percentiles": "survival_time_percentiles.csv",
    "models": "survival_cox_models.csv",
    "coefficients": "survival_cox_coefficients.csv",
    "proportional_hazards": "survival_proportional_hazards_test.csv",
    "baseline": "survival_baseline.csv",
    "residuals": "survival_schoenfeld_residuals.csv",
    "cohorts": "survival_cohorts.csv",
}
UNKNOWN = "UNKNOWN"


def settings() -> dict[str, Any]:
    """The run settings of MT19: every default, so that a change of one changes the run id.
    The method draws no random numbers, so there is no seed."""
    return {
        MT19: {
            "event": an.EVENT_CLOSED,
            "covariates": list(an.COVARIATES),
            "ties": an.TIES_DEFAULT,
            "confidence": an.CONFIDENCE,
            "time_unit": an.TIME_UNIT,
            "min_events": an.MIN_EVENTS,
            "percentiles": list(an.PERCENTILES),
            "significance": an.SIGNIFICANCE,
            "curve_rows": an.CURVE_ROWS,
        }
    }


@dataclass(frozen=True)
class SurvivalRun:
    """MT19 over all segments, or the reason it did not run."""

    tables: Mapping[str, pl.DataFrame] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    entries: tuple[Assumption, ...] = ()
    reason: str = ""
    ran: tuple[str, ...] = ()
    notes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # module ID: lines
    information: tuple[str, ...] = ()  # what the dates and the exclusions were, not refusals

    def files(self) -> dict[str, pl.DataFrame]:
        """Every table by output file name."""
        return {name: self.tables[key] for key, name in TABLES.items() if key in self.tables}


def _size_basis(inputs: MeasureInputs) -> Basis:
    """The basis CV08 sizes are on: value-date prices when the price index is loaded."""
    indexed = (
        inputs.market is not None and inputs.market.index(inputs.price_index or "") is not None
    )
    return Basis(
        ReinsuranceBasis.GROSS,
        CurrencyView.REPORTING,
        ValueBasis.INFLATION_ADJUSTED if indexed else ValueBasis.NOMINAL,
    )


def _sizes_at_report(inputs: MeasureInputs, first: pl.DataFrame) -> pl.DataFrame:
    """claim_id and the incurred at its first valuation on the basis of CV08, null where the
    first valuation has no amount or no rate applies."""
    dates = sorted(first["first_valuation"].unique().to_list())
    try:
        states, _ = amounts_at(inputs, _size_basis(inputs), "incurred", dates)
    except ConversionError:
        states, _ = amounts_at(inputs, Basis(), "incurred", dates)
    states, _ = left_out(states)
    return (
        states.join(first, left_on=["claim_id", "end"], right_on=["claim_id", "first_valuation"])
        .select("claim_id", pl.col("value").alias("size_at_report"))
        .unique("claim_id")
    )


def claim_durations(
    inputs: MeasureInputs, event: str = an.EVENT_CLOSED
) -> tuple[pl.DataFrame, list[str]]:
    """(durations frame, information lines) as `survival_analysis` takes them. `event` closed:
    the first closing in any closed status; closed_with_payment: a first closing as CLOSED is
    the event and a first closing as CLOSED_NIL ends the observation without one."""
    request = MeasureRequest()
    cut_off: date = inputs.cut_off
    head = header(inputs, request)
    rows = status_rows(inputs).sort("claim_id", "valuation_date")
    closed = pl.col("status").is_in(CLOSED)
    rows = rows.with_columns(closed.alias("is_closed"))
    closing = (
        rows.filter(pl.col("is_closed"))
        .group_by("claim_id", maintain_order=True)
        .agg(
            pl.col("valuation_date").first().alias("first_close"),
            pl.col("status").first().alias("first_kind"),
        )
    )
    reopened = (
        rows.join(closing, on="claim_id")
        .filter(~pl.col("is_closed") & (pl.col("valuation_date") > pl.col("first_close")))
        .select("claim_id")
        .unique()
        .with_columns(pl.lit(True).alias("reopened"))
    )
    classes, _ = size_classes(inputs, request)
    first = head.select("claim_id", "first_valuation")
    data = (
        head.select(
            "claim_id",
            "first_valuation",
            "segment",
            "line",
            "cause",
            "event_code",
            "report_date",
            "close_date",
        )  # fmt: skip
        .join(closing, on="claim_id", how="left")
        .join(reopened, on="claim_id", how="left")
        .join(
            classes.select("claim_id", "claim_size_class", "threshold"), on="claim_id", how="left"
        )
        .join(_sizes_at_report(inputs, first), on="claim_id", how="left")
        .with_columns(pl.col("reopened").fill_null(False))
    )
    report = pl.coalesce("report_date", "first_valuation")
    precise = (
        pl.col("close_date").is_not_null()
        & ~pl.col("reopened")
        & (pl.col("close_date") <= cut_off)
        & pl.col("first_close").is_not_null()
    )
    has_event = pl.col("first_close").is_not_null()
    if event == an.EVENT_PAID:
        has_event = has_event & (pl.col("first_kind") == PAID_CLOSING)
    end = (
        pl.when(pl.col("first_close").is_null())
        .then(pl.lit(cut_off))
        .when(precise)
        .then(pl.col("close_date"))
        .otherwise(pl.col("first_close"))
    )
    at_report = (
        pl.when(pl.col("event_code").is_not_null() & (pl.col("event_code") != UNKNOWN))
        .then(pl.lit("CATASTROPHE"))
        .when(pl.col("size_at_report").is_null())
        .then(pl.lit(UNKNOWN))
        .when(pl.col("threshold").is_not_null() & (pl.col("size_at_report") >= pl.col("threshold")))
        .then(pl.lit("LARGE"))
        .otherwise(pl.lit("ATTRITIONAL"))
    )
    frame = data.with_columns(
        report.alias("report"),
        end.alias("end"),
        has_event.alias("event"),
        (pl.col("report_date").is_null() | (pl.col("first_close").is_not_null() & ~precise)).alias(
            "approximate"
        ),
        at_report.alias("size_class_at_report"),
        pl.col("claim_size_class").alias("size_class_at_cutoff"),
    ).with_columns(
        (pl.col("end") - pl.col("report")).dt.total_days().alias("duration_days"),
        pl.col("report").dt.year().alias("report_year"),
    )
    information: list[str] = []
    late = frame.filter(pl.col("report") > cut_off)
    negative = frame.filter(pl.col("duration_days") < 0)
    if negative.height:
        information.append(
            f"{negative.height} claims closed before they were reported excluded (DV-CLM-05)"
        )
    kept = frame.filter((pl.col("report") <= cut_off) & (pl.col("duration_days") >= 0))
    if late.height:
        information.append(f"{late.height} claims reported after the cut-off excluded")
    month_end = int(kept["approximate"].sum())
    if month_end:
        information.append(
            f"{month_end} of {kept.height} durations use month-end dates taken from the claim "
            "valuations (approximations of up to one month)"
        )
    return (
        kept.select(
            "claim_id",
            "segment",
            "line",
            "cause",
            "size_class_at_report",
            "size_class_at_cutoff",
            "report_year",
            "duration_days",
            "event",
            "approximate",
        ),  # fmt: skip
        information,
    )


def _concat(parts: list[pl.DataFrame]) -> pl.DataFrame:
    return pl.concat(parts, how="vertical_relaxed") if parts else pl.DataFrame()


def run_survival(
    inputs: MeasureInputs,
    register: AssumptionsRegister,
    progress: Callable[[str], None] | None = None,
) -> SurvivalRun:
    """MT19 for every segment of the claims."""
    if not inputs.has("claim_valuations"):
        return SurvivalRun(reason="no claim valuations were loaded")
    frames: dict[str, tuple[pl.DataFrame, list[str]]] = {}
    pieces: dict[str, list[pl.DataFrame]] = {key: [] for key in TABLES}
    entries: list[Assumption] = []
    diagnostics: list[Diagnostic] = []
    notes: list[str] = []
    information: list[str] = []
    default, _ = claim_durations(inputs)
    segments = sorted(str(s) for s in default["segment"].fill_null(UNKNOWN).unique())
    if not segments:
        return SurvivalRun(reason="no claims to analyse")
    for segment in segments:
        options, used = mt19_judged(register, f"{segment}/survival")
        entries += used
        event = options["event"]
        if event not in frames:
            frames[event] = (
                (default, []) if event == an.EVENT_CLOSED else claim_durations(inputs, event)
            )
        durations, found = frames[event]
        if not information:
            information = found
        part = durations.filter(pl.col("segment").fill_null(UNKNOWN) == segment)
        result = survival_analysis(part, **options)
        diagnostics += result.diagnostics
        for key in TABLES:
            table = _frame_of(result, key)
            if table.height:
                pieces[key].append(table)
        approximate = int(part["approximate"].sum())
        if approximate:
            diagnostics.append(
                Diagnostic(
                    MT19,
                    "MONTH_END_DATES",
                    an.INFO,
                    f"{segment}: {approximate} of {part.height} durations use month-end dates "
                    "from the claim valuations (approximations of up to one month)",
                    segment,
                    float(approximate),
                )
            )
        for row in result.models.filter(pl.col("status") == an.NOT_RUN).iter_rows(named=True):
            notes.append(
                f"MT19 survival analysis: no Cox model for {row['segment']}: {row['reason']}"
            )
    tables = {key: _concat(parts) for key, parts in pieces.items()}
    ran = (MT19,) if tables["groups"].height else ()
    return SurvivalRun(
        tables,
        tuple(diagnostics),
        tuple(entries),
        ran=ran,
        notes={"M03": tuple(notes)},
        information=tuple(information),
    )


def _frame_of(result: an.Survival, key: str) -> pl.DataFrame:
    return getattr(result, key)


def diagnostic_rows(run: SurvivalRun) -> list[dict[str, Any]]:
    """The diagnostics of MT19 as rows of diagnostics.csv: the segment is the target."""
    return [
        {
            "segment": item.target.partition(" / ")[0],
            "line": "",
            "measure": "survival",
            "method": item.method,
            "code": item.code,
            "severity": item.severity,
            "target": item.target,
            "value": item.value,
            "message": item.message,
        }
        for item in run.diagnostics
    ]


def methods_run(run: SurvivalRun) -> list[str]:
    """MT19 when it produced a curve for at least one segment."""
    return list(run.ran)
