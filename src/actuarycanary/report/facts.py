"""The named facts the finding rules (RP01) and the headline tiles read, computed from a run.

Facts are plain numbers and texts with a kind that says how to show them. Thresholds are
taken from the code that owns them (decision 0039 for the diagnostics, MT08 for the flag
rate), so a rule never repeats one. Segments are never added together: segment facts sum the
lines of one segment only (blueprint 10).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import polars as pl

from actuarycanary.measures.model import MeasureResult
from actuarycanary.methods import diagnostics as limits
from actuarycanary.methods import robust_z
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.modules.anomalies import AnomalyResult
from actuarycanary.modules.reserving import SELECTION_MEASURE, GroupReserving, ReservingResult
from actuarycanary.modules.runner import AnalysisResult, ModuleState
from actuarycanary.quality.model import QualityReport
from actuarycanary.report.findings import Fact, Kind
from actuarycanary.structures.periods import Period

FactSet = dict[str, Fact]
METHOD_KEYS = ("chain_ladder", "bornhuetter_ferguson", "cape_cod", "expected_loss_ratio")


def _put(facts: FactSet, name: str, value: float | str | None, kind: Kind) -> None:
    """Add a fact when it is known; an unknown fact is simply absent."""
    if value is None:
        return
    if isinstance(value, float) and not np.isfinite(value):
        return
    facts[name] = Fact(value, kind)


def line_name(group: tuple[str, ...]) -> str:
    return " · ".join(group)


def _codes(group: GroupReserving, code: str) -> list[tuple[str, str, float | None]]:
    """(measure, target, value) of the group's diagnostics with this code."""
    return [
        (d.measure, d.item.target, d.item.value) for d in group.diagnostics if d.item.code == code
    ]


@dataclass(frozen=True)
class Reserve:
    """The selected ultimate and IBNR of one line, None where the selection is incomplete."""

    incurred: float
    ultimate: float | None

    @property
    def ibnr(self) -> float | None:
        return None if self.ultimate is None else self.ultimate - self.incurred


def selected_reserve(group: GroupReserving) -> Reserve:
    incurred = float(np.nansum(group.triangles[SELECTION_MEASURE].latest))
    selected = group.selected_ultimates()
    ultimate = None if None in selected else float(sum(v for v in selected if v is not None))
    return Reserve(incurred, ultimate)


def method_totals(group: GroupReserving, measure: str = SELECTION_MEASURE) -> dict[str, float]:
    """Total ultimate of each method on a triangle, where it covers every origin."""
    found = group.method_ultimates(measure)
    return {
        key: float(values.sum())
        for key in METHOD_KEYS
        if (values := found.get(key)) is not None and np.isfinite(values).all()
    }


def anomaly_rates(anomalies: AnomalyResult) -> dict[tuple[str, str], tuple[int, int]]:
    """(flagged, values) of MT08 per segment and line, over the groups it scored."""
    rates = anomalies.robust.flag_rates.filter(pl.col("status") == "scored")
    found: dict[tuple[str, str], tuple[int, int]] = {}
    for row in (
        rates.group_by("segment", "line")
        .agg(pl.col("flagged").sum(), pl.col("values").sum())
        .sort("segment", "line")
        .iter_rows(named=True)
    ):
        found[(row["segment"], row["line"])] = (int(row["flagged"]), int(row["values"]))
    return found


def line_facts(
    group: GroupReserving,
    anomalies: dict[tuple[str, str], tuple[int, int]],
    currency: str,
) -> FactSet:
    facts: FactSet = {}
    _put(facts, "segment", group.group[0], "text")
    _put(facts, "line", line_name(group.group), "text")
    _put(facts, "currency", currency, "text")
    _put(facts, "origin_periods", len(group.triangles["paid"].origins), "count")
    _put(facts, "thin_threshold", limits.THIN_EVIDENCE_ORIGINS, "count")
    _put(facts, "thin_evidence", len(_codes(group, "THIN_EVIDENCE")), "count")
    few = _codes(group, "FEW_LINK_RATIOS")
    _put(facts, "few_link_ratio_factors", len(few), "count")
    _put(facts, "few_link_ratio_minimum", limits.FEW_LINK_RATIOS, "count")
    _put(facts, "few_link_ratio_list", ", ".join(f"{m} {t}" for m, t, _ in few), "text")
    zero = _codes(group, "ZERO_DENOMINATOR")
    _put(facts, "zero_denominator_cells", len(zero), "count")
    _put(facts, "zero_denominator_list", ", ".join(f"{m} {t}" for m, t, _ in zero), "text")
    late = _codes(group, "LATE_DEVELOPMENT")
    _put(facts, "late_development_count", len(late), "count")
    _put(facts, "late_development_limit", limits.LATE_DEVELOPMENT_FACTOR, "factor")
    _put(
        facts,
        "late_development_list",
        ", ".join(f"{m} {t} ({_factor(v)})" for m, t, v in late),
        "text",
    )
    negative = [d for d in _codes(group, "NEGATIVE_IBNR") if d[0] == "paid"]
    _put(facts, "negative_paid_origins", len(negative), "count")
    _put(facts, "negative_paid_list", ", ".join(t for _, t, _ in negative), "text")
    reserve = selected_reserve(group)
    _put(facts, "selected_ultimate", reserve.ultimate, "amount")
    _put(facts, "selected_ibnr", reserve.ibnr, "amount")
    totals = method_totals(group)
    if len(totals) >= 2 and reserve.ultimate:
        low, high = min(totals.values()), max(totals.values())
        _put(facts, "method_low", low, "amount")
        _put(facts, "method_high", high, "amount")
        _put(facts, "method_spread", (high - low) / reserve.ultimate, "ratio")
    _put(facts, "anomaly_rate_limit", robust_z.MAX_FLAG_RATE, "ratio")
    found = anomalies.get((group.group[0], group.group[1]))
    if found is not None and found[1] > 0:
        _put(facts, "anomaly_flagged", found[0], "count")
        _put(facts, "anomaly_values", found[1], "count")
        _put(facts, "anomaly_rate", found[0] / found[1], "ratio")
    return facts


def _factor(value: float | None) -> str:
    return Fact(value, "factor").show() if value is not None else ""


def _frame(analysis: AnalysisResult, measure: str, breakdowns: tuple[str, ...]) -> pl.DataFrame:
    result = find_result(analysis, measure, breakdowns)
    return result.frame if result is not None and result.frame is not None else pl.DataFrame()


def find_result(
    analysis: AnalysisResult, measure: str, breakdowns: tuple[str, ...]
) -> MeasureResult | None:
    return next(
        (
            r
            for r in analysis.results()
            if r.measure == measure and r.request.breakdowns == breakdowns and r.available
        ),
        None,
    )


def period_complete(cut_off: date, period: Period, fiscal_start: int = 1) -> bool:
    """The cut-off closes a calendar period of this length."""
    if (cut_off + timedelta(days=1)).day != 1:
        return False
    return (cut_off.month - fiscal_start + 1) % period.months == 0


def segment_premium(analysis: AnalysisResult) -> dict[str, list[tuple[str, float]]]:
    """Written premium (PR01) per segment and calendar period, oldest first."""
    frame = _frame(analysis, "PR01", ("segment", "line", "calendar_period"))
    if frame.height == 0:
        return {}
    summed = (
        frame.filter(pl.col("value").is_not_null())
        .group_by("segment", "calendar_period")
        .agg(pl.col("value").sum())
        .sort("segment", "calendar_period")
    )
    found: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for segment, period, value in summed.iter_rows():
        found[segment].append((str(period), float(value)))
    return dict(found)


def segment_loss_ratios(analysis: AnalysisResult) -> dict[str, list[tuple[str, float]]]:
    """Ultimate loss ratio (RT01: ultimate over earned premium) per segment and origin."""
    frame = _frame(analysis, "RT01", ("segment", "line", "origin_period"))
    if frame.height == 0 or "ultimate" not in frame.columns:
        return {}
    summed = (
        frame.filter(
            pl.col("ultimate").is_not_null()
            & pl.col("earned_premium").is_not_null()
            & (pl.col("earned_premium") > 0)
        )
        .group_by("segment", "origin_period")
        .agg(pl.col("ultimate").sum(), pl.col("earned_premium").sum())
        .sort("segment", "origin_period")
    )
    found: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for segment, origin, ultimate, premium in summed.iter_rows():
        found[segment].append((str(origin), float(ultimate) / float(premium)))
    return dict(found)


def segment_facts(
    segment: str,
    groups: Iterable[GroupReserving],
    premium: list[tuple[str, float]],
    premium_comparable: bool,
    loss_ratios: list[tuple[str, float]],
    currency: str,
) -> FactSet:
    facts: FactSet = {}
    _put(facts, "segment", segment, "text")
    _put(facts, "currency", currency, "text")
    reserves = {line_name(g.group): selected_reserve(g) for g in groups}
    ultimates = [r.ultimate for r in reserves.values()]
    if reserves and None not in ultimates:
        ultimate = float(sum(u for u in ultimates if u is not None))
        incurred = sum(r.incurred for r in reserves.values())
        _put(facts, "selected_ultimate", ultimate, "amount")
        _put(facts, "selected_ibnr", ultimate - incurred, "amount")
        if ultimate:
            _put(facts, "ibnr_share", (ultimate - incurred) / ultimate, "ratio")
        largest = max(reserves, key=lambda k: (reserves[k].ibnr or 0.0, k))
        _put(facts, "largest_line", largest.split(" · ", 1)[-1], "text")
        _put(facts, "largest_line_ibnr", reserves[largest].ibnr, "amount")
    if len(premium) >= 2 and premium_comparable:
        (before, previous), (period, latest) = premium[-2], premium[-1]
        _put(facts, "premium_period", period, "text")
        _put(facts, "premium_previous_period", before, "text")
        _put(facts, "written_premium", latest, "amount")
        _put(facts, "written_premium_previous", previous, "amount")
        if previous > 0:
            _put(facts, "premium_change", latest / previous - 1, "ratio")
            _put(facts, "premium_decline", 1 - latest / previous, "ratio")
    if len(loss_ratios) >= 2:
        (before, previous), (origin, latest) = loss_ratios[-2], loss_ratios[-1]
        _put(facts, "loss_ratio_origin", origin, "text")
        _put(facts, "loss_ratio_previous_origin", before, "text")
        _put(facts, "loss_ratio_latest", latest, "ratio")
        _put(facts, "loss_ratio_previous", previous, "ratio")
        _put(facts, "loss_ratio_change", latest - previous, "ratio")
    return facts


def _listing(items: list[str]) -> str:
    return ", ".join(items)


def run_facts(
    reserving: ReservingResult,
    analysis: AnalysisResult,
    quality: QualityReport,
    anomalies: dict[tuple[str, str], tuple[int, int]],
    lines: dict[str, FactSet],
    titles: Mapping[str, str] | None = None,
) -> FactSet:
    """`lines`: the line facts by line name, which the run facts count over; `titles` the
    module titles in the language of the report (default the English ones)."""
    titles = titles or {}
    facts: FactSet = {}
    groups = reserving.groups
    _put(facts, "lines", len(groups), "count")
    _put(facts, "thin_threshold", limits.THIN_EVIDENCE_ORIGINS, "count")
    thin = [g for g in groups if _codes(g, "THIN_EVIDENCE")]
    _put(facts, "thin_lines", len(thin), "count")
    if groups:
        origins = sorted({o for g in groups for o in g.triangles["paid"].origins})
        _put(
            facts, "origin_periods", min(len(g.triangles["paid"].origins) for g in groups), "count"
        )
        _put(facts, "first_origin", origins[0], "text")
        _put(facts, "last_origin", origins[-1], "text")

    def short(name: str) -> str:
        return name.split(" · ", 1)[-1]

    def count(name: str) -> int:
        return sum(int(f[name].value) for f in lines.values() if name in f)

    def named(name: str) -> list[str]:
        return [short(k) for k, f in lines.items() if name in f and int(f[name].value) > 0]

    _put(facts, "few_link_ratio_factors", count("few_link_ratio_factors"), "count")
    _put(facts, "few_link_ratio_lines", len(named("few_link_ratio_factors")), "count")
    _put(facts, "few_link_ratio_minimum", limits.FEW_LINK_RATIOS, "count")
    _put(facts, "zero_denominator_cells", count("zero_denominator_cells"), "count")
    _put(
        facts,
        "zero_denominator_list",
        _listing(
            [
                f"{short(k)} {f['zero_denominator_list'].value}"
                for k, f in lines.items()
                if int(f["zero_denominator_cells"].value) > 0
            ]
        ),
        "text",
    )
    _put(facts, "late_development_count", count("late_development_count"), "count")
    _put(facts, "late_development_limit", limits.LATE_DEVELOPMENT_FACTOR, "factor")
    _put(
        facts,
        "late_development_list",
        _listing(
            [
                f"{short(k)} {f['late_development_list'].value}"
                for k, f in lines.items()
                if int(f["late_development_count"].value) > 0
            ]
        ),
        "text",
    )
    _put(facts, "negative_paid_origins", count("negative_paid_origins"), "count")
    _put(
        facts,
        "negative_paid_lines",
        _listing(
            [
                f"{short(k)} {f['negative_paid_list'].value}"
                for k, f in lines.items()
                if int(f["negative_paid_origins"].value) > 0
            ]
        ),
        "text",
    )
    _put(facts, "anomaly_rate_limit", robust_z.MAX_FLAG_RATE, "ratio")
    rates = {k: f["anomaly_rate"].value for k, f in lines.items() if "anomaly_rate" in f}
    above = [k for k, r in rates.items() if float(r) > robust_z.MAX_FLAG_RATE]
    _put(facts, "anomaly_lines_above", len(above), "count")
    if rates:
        highest = max(rates, key=lambda k: (float(rates[k]), k))
        _put(facts, "anomaly_rate_max", float(rates[highest]), "ratio")
        _put(facts, "anomaly_rate_max_line", short(highest), "text")
    _put(facts, "dq_score", quality.overall.value, "score")
    blocking = [f for f in quality.findings if f.severity == "BLOCKING"]
    warnings = [f for f in quality.findings if f.severity == "WARNING"]
    _put(facts, "blocking_findings", len(blocking), "count")
    _put(facts, "blocking_rows", sum(f.count for f in blocking), "count")
    _put(facts, "warning_findings", len(warnings), "count")
    _put(facts, "warning_rows", sum(f.count for f in warnings), "count")
    if warnings:
        top = max(warnings, key=lambda f: (f.count, f.rule))
        _put(facts, "top_warning", f"{top.rule}: {top.message}", "text")
    modules = analysis.modules
    skipped = [m for m in modules if m.state is ModuleState.SKIPPED]
    limited = [m for m in modules if m.state is ModuleState.LIMITED]
    _put(facts, "modules_total", len(modules), "count")
    _put(facts, "modules_ran", len(modules) - len(skipped), "count")
    _put(facts, "modules_skipped", len(skipped), "count")
    _put(
        facts,
        "skipped_list",
        _listing([f"{m.module} {titles.get(m.module, m.title)}" for m in skipped]),
        "text",
    )
    _put(facts, "modules_limited", len(limited), "count")
    _put(
        facts,
        "limited_list",
        _listing([f"{m.module} {titles.get(m.module, m.title)}" for m in limited]),
        "text",
    )
    mack = [o for g in groups for o in g.mack.values()]
    _put(facts, "mack_triangles", len(mack), "count")
    _put(facts, "mack_not_run", sum(1 for o in mack if isinstance(o, Skipped)), "count")
    return facts


__all__ = [
    "FactSet",
    "Reserve",
    "anomaly_rates",
    "find_result",
    "line_facts",
    "line_name",
    "method_totals",
    "period_complete",
    "run_facts",
    "segment_facts",
    "segment_loss_ratios",
    "segment_premium",
    "selected_reserve",
]
