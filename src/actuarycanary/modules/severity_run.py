"""MT17 and MT18 in the pipeline (records 0300, 0301, 0620).

The claim sizes are the ones CV08 classes: gross incurred at the cut-off in the reporting
currency, restated to value-date prices when the price index is loaded (`size_classes`), with
segment, line, event code and origin year from the claim header and the latest status. The
methods run once per segment and line, each with the register's entries for its scope
(`SEGMENT/LINE/severity`). The large-loss threshold stays CV08's (record 0601): MT18's
threshold is reported beside it (`ExtremeValues.threshold_comparison`) and never classifies a
claim.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from actuarycanary.measures.claim_base import header, size_classes, status_rows
from actuarycanary.measures.model import MeasureInputs, MeasureRequest
from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.diagnostics import Diagnostic
from actuarycanary.methods.severity import (
    SEED,
    ExtremeValues,
    SeverityFits,
    extreme_values,
    fit_severity,
    mt17_judged,
    mt18_judged,
)
from actuarycanary.methods.severity import evt as evt_module
from actuarycanary.methods.severity import fitting as fitting_module
from actuarycanary.methods.severity.sizes import ALL_NON_NIL, CLOSED_CLAIMS

MT17, MT18 = "MT17", "MT18"
GROUP = ("segment", "line")
FITS_TABLES = (
    "parameters",
    "fits",
    "selected",
    "quantiles",
    "limited_expected_values",
    "plots",
    "trend",
    "trend_summary",
    "groups",
)
EXTREME_TABLES = (
    "thresholds",
    "candidates",
    "gpd_fit",
    "tail_quantiles",
    "return_levels",
    "threshold_comparison",
    "mean_excess",
    "excess_plot",
    "yearly",
    "yearly_summary",
)
FILE_PREFIX = {MT17: "severity_", MT18: "extreme_"}


def settings(seed: int = SEED) -> dict[str, Any]:
    """The run settings of the severity methods: the seed and every default, so that a change
    of either changes the run id."""
    return {
        "seed": seed,
        MT17: {
            "claims_used": CLOSED_CLAIMS,
            "truncation_point": 0.0,
            "exclude_catastrophes": True,
            "significance": fitting_module.SIGNIFICANCE,
            "gof_bootstrap": fitting_module.GOF_BOOTSTRAP,
            "gof_max_claims": fitting_module.GOF_MAX_CLAIMS,
            "min_claims": fitting_module.MIN_CLAIMS,
            "candidates": list(fitting_module.DEFAULT_CANDIDATES),
        },
        MT18: {
            "claims_used": ALL_NON_NIL,
            "fdr_level": evt_module.FDR_LEVEL,
            "min_exceedances": evt_module.MIN_EXCEEDANCES,
            "gof_bootstrap": evt_module.GOF_BOOTSTRAP,
            "candidate_quantiles": list(evt_module.CANDIDATE_QUANTILES),
            "return_periods": list(evt_module.RETURN_PERIODS),
        },
    }


@dataclass(frozen=True)
class SeverityRun:
    """MT17 and MT18 over all groups, or the reason they did not run."""

    fits: Mapping[str, pl.DataFrame] = field(default_factory=dict)
    extreme: Mapping[str, pl.DataFrame] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    entries: tuple[Assumption, ...] = ()
    seed: int = SEED
    reason: str = ""
    ran: tuple[str, ...] = ()
    notes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # module ID: lines
    comparison: str = ""  # the MT18 threshold beside CV08's, for M06 (information)

    def randomness(self) -> list[dict[str, object]]:
        purposes = {
            MT17: "bootstrap p-values and the subsample of the goodness-of-fit tests",
            MT18: "Anderson-Darling bootstrap p-values of the threshold candidates",
        }
        return [
            {"method": m, "seed": self.seed, "purpose": purposes[m]}
            for m in self.ran
            if m in purposes
        ]

    def files(self) -> dict[str, pl.DataFrame]:
        """Every table by output file name."""
        found: dict[str, pl.DataFrame] = {}
        for method, tables in ((MT17, self.fits), (MT18, self.extreme)):
            for name, frame in tables.items():
                found[f"{FILE_PREFIX[method]}{name}.csv"] = frame
        return found


def claim_sizes(inputs: MeasureInputs) -> tuple[pl.DataFrame, dict[tuple[str, ...], float | None]]:
    """(sizes frame, CV08 threshold by group) as the methods take them (record 0300)."""
    request = MeasureRequest()
    classes, _ = size_classes(inputs, request)
    head = header(inputs, request).select(
        "claim_id",
        "segment",
        "line",
        "event_code",
        pl.col("origin_period").cast(pl.String).str.slice(0, 4).cast(pl.Int64, strict=False),
    )
    status = (
        status_rows(inputs)
        .sort("claim_id", "valuation_date")
        .group_by("claim_id", maintain_order=True)
        .agg(pl.col("status").last())
    )
    frame = (
        classes.join(head, on="claim_id")
        .join(status, on="claim_id")
        .rename({"origin_period": "origin_year"})
        .select(
            "claim_id", "size", "status", "segment", "line", "event_code", "origin_year",
            "claim_size_class", "threshold",
        )
    )  # fmt: skip
    thresholds: dict[tuple[str, ...], float | None] = {
        (s, line): t
        for s, line, t in frame.group_by(*GROUP).agg(pl.col("threshold").first()).iter_rows()
    }
    return frame, thresholds


def _merge(parts: list[pl.DataFrame]) -> pl.DataFrame:
    parts = [p for p in parts if p.width]
    return pl.concat(parts, how="diagonal_relaxed") if parts else pl.DataFrame()


def _refusals(
    method: str, label: str, table: pl.DataFrame | None, ok: tuple[str, ...]
) -> list[str]:
    """One line per reason: which groups the method did not run for."""
    if table is None or table.height == 0 or "status" not in table.columns:
        return []
    by_reason: dict[str, list[str]] = {}
    for segment, line, status, reason in table.select(*GROUP, "status", "reason").iter_rows():
        if status not in ok:
            by_reason.setdefault(str(reason), []).append(f"{segment} / {line}")
    return [
        f"{method} {label} did not run for {', '.join(groups)}: {reason}"
        for reason, groups in sorted(by_reason.items())
    ]


def run_severity(
    inputs: MeasureInputs,
    register: AssumptionsRegister,
    seed: int = SEED,
    progress: Callable[[str], None] | None = None,
) -> SeverityRun:
    """MT17 and MT18 for every segment and line of the claims."""
    if not inputs.has("claim_valuations"):
        return SeverityRun(seed=seed, reason="no claim valuations were loaded")
    sizes, thresholds = claim_sizes(inputs)
    if sizes.height == 0:
        return SeverityRun(seed=seed, reason="no claim sizes: there are no claims to fit")
    entries: list[Assumption] = []
    fits: list[SeverityFits] = []
    extremes: list[ExtremeValues] = []
    for (segment, line), part in sorted(
        sizes.group_by(*GROUP, maintain_order=True), key=lambda kv: tuple(map(str, kv[0]))
    ):
        scope = "/".join((str(segment), str(line), "severity"))
        options17, used17 = mt17_judged(register, scope)
        options18, used18 = mt18_judged(register, scope)
        entries += [*used17, *used18]
        key = (str(segment), str(line))
        fits.append(fit_severity(part, seed=seed, **options17))
        extremes.append(
            extreme_values(part, cv08_thresholds={key: thresholds.get(key)}, seed=seed, **options18)
        )
    fit_tables = {n: _merge([getattr(f, n) for f in fits]) for n in FITS_TABLES}
    extreme_tables = {n: _merge([getattr(e, n) for e in extremes]) for n in EXTREME_TABLES}
    diagnostics = tuple(d for f in fits for d in f.diagnostics) + tuple(
        d for e in extremes for d in e.diagnostics
    )
    notes = {
        "M03": tuple(_refusals(MT17, "severity fits", fit_tables.get("groups"), ("fitted",))),
        "M06": tuple(
            _refusals(
                MT18, "extreme values", extreme_tables.get("thresholds"), (evt_module.FITTED,)
            )
        ),
    }
    return SeverityRun(
        fit_tables,
        extreme_tables,
        diagnostics,
        tuple(entries),
        seed,
        ran=tuple(_ran(fit_tables, extreme_tables)),
        notes=notes,
        comparison=comparison_note(extreme_tables.get("threshold_comparison")),
    )


def _ran(fits: Mapping[str, pl.DataFrame], extreme: Mapping[str, pl.DataFrame]) -> list[str]:
    """The methods that fitted for at least one group."""

    def any_ok(table: pl.DataFrame | None, ok: str) -> bool:
        return (
            table is not None and "status" in table.columns and bool((table["status"] == ok).any())
        )

    found: list[str] = []
    if any_ok(fits.get("groups"), "fitted"):
        found.append(MT17)
    if any_ok(extreme.get("thresholds"), evt_module.FITTED):
        found.append(MT18)
    return found


def comparison_note(table: pl.DataFrame | None) -> str:
    """The extreme-value threshold beside the CV08 threshold, per group, as one sentence for
    M06. It is information: MT18's threshold never classifies a claim (record 0601)."""
    if table is None or table.height == 0:
        return ""
    parts: list[str] = []
    for row in table.sort(*GROUP).iter_rows(named=True):
        u, c = row.get("extreme_value_threshold"), row.get("cv08_threshold")
        if u is None:
            continue
        beside = f"{c:,.0f}" if c is not None else "none"
        parts.append(f"{row['segment']} / {row['line']} {u:,.0f} against {beside}")
    if not parts:
        return ""
    return (
        "MT18 extreme-value threshold beside the CV08 large-loss threshold (reported, not used "
        "to classify claims): " + "; ".join(parts)
    )


def diagnostic_rows(run: SeverityRun) -> list[dict[str, Any]]:
    """The diagnostics of MT17 and MT18 as rows of diagnostics.csv: the group is the target."""
    rows: list[dict[str, Any]] = []
    for item in run.diagnostics:
        segment, _, line = item.target.partition(" / ")
        rows.append(
            {
                "segment": segment,
                "line": line,
                "measure": "severity",
                "method": item.method,
                "code": item.code,
                "severity": item.severity,
                "target": item.target,
                "value": item.value,
                "message": item.message,
            }
        )
    return rows


def methods_run(run: SeverityRun) -> list[str]:
    """MT17 and MT18 when they produced a result for at least one group."""
    return list(run.ran)
