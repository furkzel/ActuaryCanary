"""Everything the executive report shows, as plain data (blueprint 11, decision 0071).

`build_model` turns the results of a run into one JSON-ready dictionary: the cover, banners,
key findings, headline tiles, one page per module that ran, the reserving page per line,
what did not run, and the appendices. Every number is rounded here (CV06) and every table
and figure carries the spec IDs, versions and basis it rests on; table rows name the
measure rows behind them, which `lineage.csv` resolves to spreadsheet rows. The page is
drawn from this dictionary alone, and the golden test compares it (decision 0074).
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.canonical.feeds import Finding
from actuarycanary.convert.views import ORIGINAL, UNIT_LABEL, currency_of
from actuarycanary.manifest.metadata import ProjectMetadata
from actuarycanary.manifest.run import InputRecord, OutputRecord, SpecRecord
from actuarycanary.methods.assumptions import Assumption
from actuarycanary.modules.anomalies import AnomalyResult
from actuarycanary.modules.reserving import SELECTION_MEASURE, GroupReserving, ReservingResult
from actuarycanary.modules.runner import AnalysisResult, ModuleOutcome, ModuleState
from actuarycanary.quality.model import QualityReport
from actuarycanary.quality.output import show_score
from actuarycanary.report import charts, language, numbers
from actuarycanary.report.facts import (
    FactSet,
    anomaly_rates,
    find_result,
    line_facts,
    line_name,
    period_complete,
    run_facts,
    segment_facts,
    segment_loss_ratios,
    segment_premium,
    selected_reserve,
)
from actuarycanary.report.findings import KEY_FINDINGS, Facts, KeyFinding, evaluate
from actuarycanary.report.language import t
from actuarycanary.report.methods_section import assumption_rows, group_methods
from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.structures.triangles import MEASURES, THIN_CELL_CLAIMS

MODULE_ANCHORS = {
    "M01": "data",
    "M02": "portfolio",
    "M03": "claims",
    "M04": "reserving",
    "M05": "profitability",
    "M06": "anomalies",
}
TOP_FLAGS = 10  # anomaly flags listed on the page; all are in anomalies.csv


@dataclass(frozen=True)
class ReportInputs:
    metadata: ProjectMetadata
    run_id: str
    package_version: str
    catalogue: SpecCatalogue
    reserving: ReservingResult
    earlier: ReservingResult | None  # the selection at the previous valuation point
    analysis: AnalysisResult
    quality: QualityReport
    anomalies: AnomalyResult
    data_findings: tuple[Finding, ...]
    inputs: tuple[InputRecord, ...]
    specs: tuple[SpecRecord, ...]
    settings: Mapping[str, Any]
    outputs: tuple[OutputRecord, ...]  # the files written before the report
    randomness: tuple[Mapping[str, Any], ...] = ()
    mappings: tuple[Mapping[str, Any], ...] = ()
    lineage: Mapping[str, int] = field(default_factory=dict)  # Lineage.summary(), either format


class _Specs:
    """Spec IDs with their versions for footnotes, from the whole catalogue."""

    def __init__(self, catalogue: SpecCatalogue) -> None:
        self.versions = {f.spec.id: f.spec.version for f in catalogue.files}

    def __call__(self, *ids: str) -> str:
        return ", ".join(f"{i} v{self.versions[i]}" if i in self.versions else i for i in ids)


def _rows(frame: pl.DataFrame | None) -> pl.DataFrame:
    """The frame with the row index that lineage.csv and measures.csv use."""
    if frame is None:
        return pl.DataFrame()
    return frame.with_row_index("_row")


def basis_text(label: str) -> str:
    """A basis label such as "GROSS, REPORTING, NOMINAL" in the language of the report."""
    return ", ".join(t(part) for part in label.split(", "))


def _business(
    found: Any, measure: str, title: str, by: Sequence[str] = ("calendar_period",)
) -> list[dict[str, Any]]:
    """The last two periods of an all-business measure: one entry, or in the ORIGINAL currency
    view one per currency, because amounts of different currencies are never added."""
    if found is None or found.frame is None:
        return []
    frame = _rows(found.frame).sort("calendar_period")
    if "currency" in frame.columns:
        parts = [
            (f" [{c}]", frame.filter(pl.col("currency") == c))
            for c in sorted(set(frame["currency"]))
        ]
    else:
        parts = [("", frame)]
    out = []
    for suffix, part in parts:
        tail = part.tail(2).to_dicts()
        out.append(
            {
                "measure": f"{measure} {title}{suffix}",
                "basis": basis_text(found.request.basis.label()),
                "points": [
                    {
                        "period": str(x["calendar_period"]),
                        "value": numbers.ratio(_value(x["value"])),
                    }
                    for x in tail
                ],
                "ref": _ref(measure, by, [x["_row"] for x in tail]),
            }
        )
    return out


def _ref(measure: str, breakdowns: Sequence[str], rows: Iterable[int]) -> str:
    found = sorted(set(int(r) for r in rows))
    view = ",".join(breakdowns) or "all"
    shown = ", ".join(str(r) for r in found) if found else "none"
    return f"{measure} [{view}] rows {shown}"


def _value(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if np.isfinite(value) else None


# --- cover ----------------------------------------------------------------------------


def _cover(r: ReportInputs) -> dict[str, Any]:
    triangles = r.reserving.triangles
    settings = triangles.settings
    segments = sorted({g.group[0] for g in r.reserving.groups})
    bases = (
        f"{t(settings.reinsurance_basis.value)}, {shown_currency(triangles.reporting_currency)}, "
        f"{t(settings.value_basis.value.replace('_', ' '))}"
    )
    rows = [
        (t("Run id"), r.run_id),
        (t("Valuation date"), triangles.cut_off.isoformat()),
        (t("Segments"), ", ".join(segments) or numbers.EMPTY),
        (t("Lines"), str(len(r.reserving.groups))),
        (t("Bases"), bases),
        (
            t("Origins"),
            t(
                "{period} periods on the {axis} axis, development {development}",
                period=t(settings.origin_period.value.lower()),
                axis=t(settings.origin_axis.value),
                development=t(settings.development_period.value.lower()),
            ),
        ),
        (t("Claims used"), numbers.count(triangles.claims_used)),
        (t("Inputs"), ", ".join(i.name for i in r.inputs)),
        (t("Software"), f"{r.metadata.name} {r.package_version}"),
    ]
    if original_view(r):
        rows.append(
            (
                t("Currency view"),
                t("ORIGINAL: nothing is converted; every line is kept apart per currency"),
            )
        )
    if triangles.value_date is not None:
        rows.append(
            (
                t("Value basis"),
                t(
                    "inflation-adjusted, at the prices of {date} ({index})",
                    date=triangles.value_date.isoformat(),
                    index=triangles.price_index,
                ),
            )
        )
    for label, value in ((t("Author"), r.metadata.author), (t("Contact"), r.metadata.contact)):
        if value:
            rows.append((label, value))
    return {
        "title": r.metadata.name,
        "tagline": t(r.metadata.tagline),
        "rows": [{"label": k, "value": v} for k, v in rows],
    }


# --- tiles ----------------------------------------------------------------------------


def shown_currency(currency: str) -> str:
    """The currency as the report names it: the code, or "orig." in the ORIGINAL view."""
    return t(currency) if currency == UNIT_LABEL else currency


def original_view(r: "ReportInputs") -> bool:
    return str(r.settings.get("bases", {}).get("currency", "")) == ORIGINAL


def mixed_currencies(groups: Sequence[GroupReserving], r: "ReportInputs") -> bool:
    """The ORIGINAL view with lines of more than one currency: their amounts are not added."""
    return original_view(r) and len({currency_of(g.group[1]) for g in groups}) > 1


def _tile(
    label: str,
    value: str,
    change: str,
    against: str,
    source: str,
    note: str = "",
) -> dict[str, str]:
    return {
        "label": label,
        "value": value,
        "change": change,
        "against": against,
        "source": source,
        "note": note,
    }


def _earlier_groups(r: ReportInputs) -> dict[tuple[str, ...], GroupReserving]:
    return {g.group: g for g in r.earlier.groups} if r.earlier is not None else {}


def _tiles(r: ReportInputs, spec: _Specs, segment_sets: dict[str, FactSet]) -> list[dict[str, Any]]:
    triangles = r.reserving.triangles
    currency = shown_currency(triangles.reporting_currency)
    earlier = _earlier_groups(r)
    earlier_date = r.earlier.triangles.cut_off.isoformat() if r.earlier is not None else ""
    settings = triangles.settings
    basis = f"{t(settings.reinsurance_basis.value)}, {currency}, {t(settings.value_basis.value)}"
    premium = segment_premium(r.analysis)
    ratios = segment_loss_ratios(r.analysis)
    complete = period_complete(
        triangles.cut_off,
        triangles.settings.origin_period,
        triangles.settings.fiscal_year_start_month,
    )
    out: list[dict[str, Any]] = []
    for segment in sorted({g.group[0] for g in r.reserving.groups}):
        groups = [g for g in r.reserving.groups if g.group[0] == segment]
        facts = segment_sets.get(segment, {})
        tiles: list[dict[str, str]] = []
        if mixed_currencies(groups, r):
            note = t(
                "the lines of this segment are in different currencies and are not added: see "
                "the lines on the reserving page"
            )
            tiles.append(_tile(t("Amounts in several currencies"), numbers.EMPTY, "", "", "", note))
            out.append(
                {
                    "segment": segment,
                    "colour": charts.SEGMENT_TOKENS.get(segment, ""),
                    "tiles": tiles,
                }
            )
            continue
        series = premium.get(segment, [])
        if series:
            period, latest = series[-1]
            change, against, note = numbers.EMPTY, "", ""
            if len(series) >= 2 and complete:
                before, previous = series[-2]
                change = numbers.change_ratio(latest / previous - 1 if previous else None)
                against = t("against {period}", period=before)
            elif not complete:
                note = t("{period} is open at the valuation date: no comparison", period=period)
            tiles.append(
                _tile(
                    t("Written premium {period}", period=period),
                    f"{numbers.amount(latest)} {currency}",
                    change,
                    against,
                    f"{spec('PR01')} · {basis}",
                    note,
                )
            )
        incurred = sum(float(np.nansum(g.triangles["incurred"].latest)) for g in groups)
        before = [earlier.get(g.group) for g in groups]
        earlier_incurred = (
            sum(float(np.nansum(e.triangles["incurred"].latest)) for e in before if e is not None)
            if all(e is not None for e in before) and before
            else None
        )
        tiles.append(
            _tile(
                t("Incurred to date"),
                f"{numbers.amount(incurred)} {currency}",
                numbers.change_amount(
                    None if earlier_incurred is None else incurred - earlier_incurred
                ),
                t("against {period}", period=earlier_date) if earlier_incurred is not None else "",
                f"{spec('CL03', 'MT01')} · {basis}",
            )
        )
        points = ratios.get(segment, [])
        if points:
            origin, latest_ratio = points[-1]
            change, against = numbers.EMPTY, ""
            if len(points) >= 2:
                change = numbers.change_points(latest_ratio - points[-2][1])
                against = t("against origin {origin}", origin=points[-2][0])
            tiles.append(
                _tile(
                    t("Ultimate loss ratio, origin {origin}", origin=origin),
                    numbers.ratio(latest_ratio),
                    change,
                    against,
                    f"{spec('RT01', 'MT10')} · {basis}",
                )
            )
        ibnr = _value(facts["selected_ibnr"].value) if "selected_ibnr" in facts else None
        earlier_ibnr = None
        if all(e is not None for e in before) and before:
            reserves = [selected_reserve(e) for e in before if e is not None]
            if all(x.ibnr is not None for x in reserves):
                earlier_ibnr = float(sum(x.ibnr for x in reserves if x.ibnr is not None))
        ranged = [g for g in groups if charts.reserve_range(g, currency) is not None]
        range_note = (
            t("range per line on the reserving page; ranges of lines do not add up")
            if ranged
            else t("no range: the Mack standard error did not run")
        )
        tiles.append(
            _tile(
                t("Reserve estimate (IBNR, selected)"),
                f"{numbers.amount(ibnr)} {currency}",
                numbers.change_amount(
                    None if ibnr is None or earlier_ibnr is None else ibnr - earlier_ibnr
                ),
                t("against {period}", period=earlier_date) if earlier_ibnr is not None else "",
                f"{spec('RS02', 'MT10', 'RS03')} · {basis}",
                range_note,
            )
        )
        out.append(
            {"segment": segment, "colour": charts.SEGMENT_TOKENS.get(segment, ""), "tiles": tiles}
        )
    return out


def _quality_tile(r: ReportInputs, spec: _Specs) -> dict[str, str]:
    return _tile(
        t("Data quality score"),
        f"{show_score(r.quality.overall)} / 100",
        numbers.EMPTY,
        t("no earlier run to compare"),
        t("{spec} · {rules} rules", spec=spec("DQ01"), rules=r.quality.overall.rules),
        t(
            "{blocking} blocking, {warning} warning findings",
            blocking=r.quality.count("BLOCKING"),
            warning=r.quality.count("WARNING"),
        ),
    )


# --- module pages ---------------------------------------------------------------------


def module_title(catalogue: SpecCatalogue, outcome: ModuleOutcome) -> str:
    """The module's title in the language of the report (the specification has both)."""
    found = catalogue.modules.get(outcome.module)
    if found is not None and language.current() == language.TURKISH:
        return found.title_tr
    return outcome.title


def _module_header(
    outcome: ModuleOutcome, catalogue: SpecCatalogue, spec: _Specs
) -> dict[str, Any]:
    return {
        "module": outcome.module,
        "title": module_title(catalogue, outcome),
        "question": t(outcome.question),
        "state": t(outcome.state.value),
        "reasons": [t(x) for x in outcome.reasons],
        "anchor": MODULE_ANCHORS.get(outcome.module, outcome.module.lower()),
        "spec": spec(outcome.module),
    }


def _per_line(
    frame: pl.DataFrame, column: str = "value"
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    found: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in frame.iter_rows(named=True):
        found[(row["segment"], row["line"])].append(row)
    return found


def _lines(r: ReportInputs) -> list[tuple[str, str]]:
    return [(g.group[0], g.group[1]) for g in r.reserving.groups]


def _data_page(r: ReportInputs, spec: _Specs) -> dict[str, Any]:
    coverage = [
        {
            "concept": c.concept,
            "loaded": c.loaded,
            "rows": numbers.count(c.rows) if c.loaded else numbers.EMPTY,
            "first": c.first.isoformat() if c.first else numbers.EMPTY,
            "last": c.last.isoformat() if c.last else numbers.EMPTY,
            "score": show_score(r.quality.by_concept[c.concept])
            if c.concept in r.quality.by_concept
            else numbers.EMPTY,
        }
        for c in r.quality.coverage
    ]
    return {
        "score": show_score(r.quality.overall),
        "coverage": coverage,
        "footnote": t(
            "{spec}; rows as read from the spreadsheets; scores out of 100.", spec=spec("DQ01")
        ),
    }


def _portfolio_page(r: ReportInputs, spec: _Specs, figures: dict[str, Any]) -> dict[str, Any]:
    pr01 = find_result(r.analysis, "PR01", ("segment", "line", "calendar_period"))
    pr02 = find_result(r.analysis, "PR02", ("segment", "line", "calendar_period"))
    pr03 = find_result(r.analysis, "PR03", ("segment", "line"))
    pr06 = find_result(r.analysis, "PR06", ("segment", "line", "calendar_period"))
    written = _per_line(_rows(pr01.frame)) if pr01 else {}
    earned = _per_line(_rows(pr02.frame)) if pr02 else {}
    unearned = _per_line(_rows(pr03.frame)) if pr03 else {}
    average = _per_line(_rows(pr06.frame)) if pr06 else {}
    rows: list[dict[str, Any]] = []
    latest_period = ""
    bars: list[tuple[str, str, float | None]] = []
    for key in sorted(set(written) | set(_lines(r))):
        series = sorted(written.get(key, []), key=lambda x: str(x["calendar_period"]))
        last = series[-1] if series else None
        prev = series[-2] if len(series) >= 2 else None
        latest_period = str(last["calendar_period"]) if last else latest_period
        last_value = _value(last["value"]) if last else None
        prev_value = _value(prev["value"]) if prev else None
        ep = sorted(earned.get(key, []), key=lambda x: str(x["calendar_period"]))
        avg = sorted(average.get(key, []), key=lambda x: str(x["calendar_period"]))
        upr = unearned.get(key, [])
        refs = [
            _ref("PR01", ("segment", "line", "calendar_period"), [x["_row"] for x in series[-2:]]),
            _ref("PR02", ("segment", "line", "calendar_period"), [x["_row"] for x in ep[-1:]]),
            _ref("PR03", ("segment", "line"), [x["_row"] for x in upr]),
        ]
        rows.append(
            {
                "line": f"{key[0]} · {key[1]}",
                "segment": key[0],
                "previous": numbers.amount(prev_value),
                "latest": numbers.amount(last_value),
                "change": numbers.change_ratio(
                    last_value / prev_value - 1 if last_value is not None and prev_value else None
                ),
                "earned": numbers.amount(_value(ep[-1]["value"]) if ep else None),
                "unearned": numbers.amount(_value(upr[0]["value"]) if upr else None),
                "average": numbers.amount(_value(avg[-1]["value"]) if avg else None),
                "ref": "; ".join(refs),
            }
        )
        bars.append((key[0], key[1], last_value))
    currency = shown_currency(r.reserving.triangles.reporting_currency)
    figure = charts.bars_by_line(
        t("Written premium {period} by line, {currency}", period=latest_period, currency=currency),
        t("Written premium ({currency})", currency=currency),
        bars,
        f"%{{y}}: %{{x:,.0f}} {currency}<extra></extra>",
    )
    if figure is not None:
        figures["portfolio-written"] = figure
    business = []
    for measure, title in (
        ("PR04", t("Cancellation rate")),
        ("PR05", t("Retention ratio")),
    ):
        business += _business(
            find_result(r.analysis, measure, ("calendar_period",)), measure, title
        )
    return {
        "period": latest_period,
        "rows": rows,
        "business": business,
        "figure": "portfolio-written" if figure is not None else "",
        "footnote": t(
            "{currency}, {basis}. Written premium {pr01} by calendar period; earned {pr02} in "
            "the latest period; unearned at the valuation date {pr03}; average premium {pr06}. "
            "Each line's colour is its segment.",
            currency=currency,
            basis=basis_text(pr01.request.basis.label()) if pr01 else "",
            pr01=spec("PR01"),
            pr02=spec("PR02"),
            pr03=spec("PR03"),
            pr06=spec("PR06"),
        ),
    }


def _claims_page(r: ReportInputs, spec: _Specs, figures: dict[str, Any]) -> dict[str, Any]:
    by = ("segment", "line", "origin_period")
    results = {m: find_result(r.analysis, m, by) for m in ("CL01", "CL02", "CL03", "CL07", "CL12")}
    counts = find_result(r.analysis, "CL04", ("segment", "line"))
    settlement = find_result(r.analysis, "CL08", ("segment", "line"))
    tables = {m: _per_line(_rows(x.frame)) if x else {} for m, x in results.items()}
    count_rows = _per_line(_rows(counts.frame)) if counts else {}
    settle_rows = _per_line(_rows(settlement.frame)) if settlement else {}
    rows: list[dict[str, Any]] = []
    bars: list[tuple[str, str, float | None]] = []
    for key in sorted(set(_lines(r)) | set(count_rows)):

        def total(measure: str, column: str = "value", key: tuple[str, str] = key) -> float | None:
            found = [_value(x[column]) for x in tables[measure].get(key, [])]
            known = [v for v in found if v is not None]
            return float(sum(known)) if known else None

        reported = next(
            (_value(x["value"]) for x in count_rows.get(key, []) if x["count_type"] == "reported"),
            None,
        )
        open_ = next(
            (_value(x["value"]) for x in count_rows.get(key, []) if x["count_type"] == "open"),
            None,
        )
        delays = tables["CL07"].get(key, [])
        weighted = [(_value(x["value"]), _value(x["n"])) for x in delays]
        weighted = [(v, n) for v, n in weighted if v is not None and n]
        delay = sum(v * n for v, n in weighted) / sum(n for _, n in weighted) if weighted else None
        large = total("CL12", "large")
        base = total("CL12", "denominator")
        settle = settle_rows.get(key, [])
        incurred = total("CL03")
        rows.append(
            {
                "line": f"{key[0]} · {key[1]}",
                "reported": numbers.count(reported),
                "open": numbers.count(open_),
                "paid": numbers.amount(total("CL01")),
                "case": numbers.amount(total("CL02")),
                "incurred": numbers.amount(incurred),
                "delay": numbers.count(delay),
                "settlement": numbers.count(_value(settle[0]["value"]) if settle else None),
                "large_share": numbers.ratio(large / base if large is not None and base else None),
                "ref": "; ".join(
                    [
                        _ref(
                            "CL04",
                            ("segment", "line"),
                            [x["_row"] for x in count_rows.get(key, [])],
                        )
                    ]
                    + [
                        _ref(m, by, [x["_row"] for x in tables[m].get(key, [])])
                        for m in ("CL01", "CL02", "CL03", "CL07", "CL12")
                    ]
                ),
            }
        )
        bars.append((key[0], key[1], incurred))
    currency = shown_currency(r.reserving.triangles.reporting_currency)
    figure = charts.bars_by_line(
        t("Incurred to date by line, {currency}", currency=currency),
        t("Incurred ({currency})", currency=currency),
        bars,
        f"%{{y}}: %{{x:,.0f}} {currency}<extra></extra>",
    )
    if figure is not None:
        figures["claims-incurred"] = figure
    basis = basis_text(results["CL03"].request.basis.label()) if results["CL03"] else ""
    return {
        "rows": rows,
        "figure": "claims-incurred" if figure is not None else "",
        "footnote": t(
            "{currency}, {basis}; all origin periods to the valuation date. Claim counts "
            "{cl04}; paid {cl01}, case reserve {cl02}, incurred {cl03}; mean reporting delay "
            "in days {cl07} weighted by claims; mean settlement time in days {cl08}; "
            "large-loss share of incurred {cl12}. Each line's colour is its segment.",
            currency=currency,
            basis=basis,
            cl04=spec("CL04"),
            cl01=spec("CL01"),
            cl02=spec("CL02"),
            cl03=spec("CL03"),
            cl07=spec("CL07"),
            cl08=spec("CL08"),
            cl12=spec("CL12"),
        ),
    }


def _profitability_page(r: ReportInputs, spec: _Specs, figures: dict[str, Any]) -> dict[str, Any]:
    by = ("segment", "line", "origin_period")
    rt01 = find_result(r.analysis, "RT01", by)
    rt02 = find_result(r.analysis, "RT02", by)
    ratios = _per_line(_rows(rt01.frame)) if rt01 else {}
    combined = _per_line(_rows(rt02.frame)) if rt02 else {}
    lines: list[dict[str, Any]] = []
    for n, key in enumerate(sorted(set(ratios) | set(_lines(r)))):
        rows = sorted(ratios.get(key, []), key=lambda x: str(x["origin_period"]))
        by_origin = {str(x["origin_period"]): x for x in combined.get(key, [])}
        table = []
        for x in rows:
            origin = str(x["origin_period"])
            c = by_origin.get(origin)
            table.append(
                {
                    "origin": origin,
                    "earned": numbers.amount(_value(x.get("earned_premium"))),
                    "incurred": numbers.amount(_value(x.get("incurred"))),
                    "ultimate": numbers.amount(_value(x.get("ultimate"))),
                    "incurred_ratio": numbers.ratio(_value(x.get("incurred_ratio"))),
                    "ultimate_ratio": numbers.ratio(_value(x.get("ultimate_ratio"))),
                    "combined": numbers.ratio(_value(c["value"]) if c else None),
                    "ref": "; ".join(
                        [_ref("RT01", by, [x["_row"]])]
                        + ([_ref("RT02", by, [c["_row"]])] if c else [])
                    ),
                }
            )
        figure_id = f"profitability-{n}"
        figure = charts.ratio_by_origin(
            t("Ultimate loss ratio by origin, {line}", line=key[1]),
            key[0],
            [(str(x["origin_period"]), _value(x.get("ultimate_ratio"))) for x in rows],
        )
        if figure is not None:
            figures[figure_id] = figure
        lines.append(
            {
                "line": f"{key[0]} · {key[1]}",
                "rows": table,
                "figure": figure_id if figure is not None else "",
            }
        )
    expenses = []
    for measure, title in (
        ("EX01", t("Commission ratio")),
        ("EX02", t("Expense ratio")),
        ("EX03", t("Claims handling ratio")),
    ):
        expenses += _business(
            find_result(r.analysis, measure, ("calendar_period",)), measure, title
        )
    currency = shown_currency(r.reserving.triangles.reporting_currency)
    basis = basis_text(rt01.request.basis.label()) if rt01 else ""
    return {
        "lines": lines,
        "expenses": expenses,
        "figure_note": t(
            "Ultimate loss ratio per origin: selected ultimate over earned premium "
            "({specs}), {basis}; one chart per line in the colour of its segment, each "
            "starting at zero.",
            specs=spec("RT01", "MT10", "PR02"),
            basis=basis,
        ),
        "footnote": t(
            "{currency}, {basis}. Loss ratios {rt01} over earned premium {pr02}; the ultimate "
            "is the selected ultimate {mt10}; combined ratio {rt02}. Expense ratios are for "
            "all business together, the one combined view the blueprint allows (section 10).",
            currency=currency,
            basis=basis,
            rt01=spec("RT01"),
            pr02=spec("PR02"),
            mt10=spec("MT10"),
            rt02=spec("RT02"),
        ),
    }


def _anomalies_page(
    r: ReportInputs,
    spec: _Specs,
    figures: dict[str, Any],
    rates: dict[tuple[str, str], tuple[int, int]],
) -> dict[str, Any]:
    from actuarycanary.methods import robust_z

    flags = r.anomalies.flags
    isolation = (
        flags.filter(pl.col("method") == "MT09").group_by("segment", "line").agg(pl.len())
        if flags.height
        else pl.DataFrame(schema={"segment": pl.String, "line": pl.String, "len": pl.UInt32})
    )
    by_line = {(s, line): int(n) for s, line, n in isolation.iter_rows()}
    rows = []
    bars: list[tuple[str, str, float | None]] = []
    for key in sorted(set(_lines(r)) | set(rates)):
        flagged, values = rates.get(key, (0, 0))
        rate = flagged / values if values else None
        rows.append(
            {
                "line": f"{key[0]} · {key[1]}",
                "scored": numbers.count(values) if values else t("not scored"),
                "flagged": numbers.count(flagged) if values else numbers.EMPTY,
                "rate": numbers.ratio(rate),
                "above": rate is not None and rate > robust_z.MAX_FLAG_RATE,
                "isolation": numbers.count(by_line.get(key, 0)),
            }
        )
        bars.append((key[0], key[1], rate))
    figure = charts.bars_by_line(
        t("Share of values flagged by the robust z-score, by line"),
        t("Share flagged"),
        bars,
        "%{y}: %{x:.1%}<extra></extra>",
        limit=robust_z.MAX_FLAG_RATE,
    )
    if figure is not None:
        figure["layout"]["xaxis"]["tickformat"] = ".0%"
        figures["anomalies-rate"] = figure
    top = (
        flags.with_columns(pl.col("score").abs().alias("_size"))
        .sort(["_size", "method", "claim_id"], descending=[True, False, False], nulls_last=True)
        .head(TOP_FLAGS)
        if flags.height
        else flags
    )
    return {
        "rows": rows,
        "figure": "anomalies-rate" if figure is not None else "",
        "limit": numbers.ratio(robust_z.MAX_FLAG_RATE),
        "total": numbers.count(flags.height),
        "top": [
            {
                "method": x["method"],
                "claim": x["claim_id"],
                "line": f"{x['segment']} · {x['line']}",
                "date": x["valuation_date"].isoformat() if x["valuation_date"] else "",
                "variable": t(x["variable"].replace("_", " ")),
                "score": numbers.factor(_value(x["score"])),
                "reason": x["reason"],
                "source": f"{x['file']} [{x['sheet']}] rows {x['rows']}",
            }
            for x in top.to_dicts()
        ],
        "footnote": t(
            "Robust z-score {mt08} on payments and case-reserve movements per line, isolation "
            "forest {mt09} on claims per segment; the dashed line is the flag rate above which "
            "MT08 warns that a group may mix populations. Flags are leads for a reviewer, not "
            "errors; anomalies.csv lists every flag with its rows.",
            mt08=spec("MT08"),
            mt09=spec("MT09"),
        ),
    }


# --- reserving ------------------------------------------------------------------------


def _line_anchor(n: int) -> str:
    return f"line-{n}"


def _reserving(
    r: ReportInputs,
    spec: _Specs,
    figures: dict[str, Any],
    line_findings: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    triangles = r.reserving.triangles
    currency = shown_currency(triangles.reporting_currency)
    basis = (
        f"{t(triangles.settings.reinsurance_basis.value)}, "
        f"{t(triangles.settings.value_basis.value)}, {currency}"
    )
    summary = []
    lines = []
    for n, group in enumerate(r.reserving.groups):
        name = line_name(group.group)
        anchor = _line_anchor(n)
        totals = group.totals()
        reserve = selected_reserve(group)
        summary.append(
            {
                "line": name,
                "anchor": anchor,
                "paid": numbers.amount(totals.paid),
                "incurred": numbers.amount(totals.incurred),
                "ult_paid": numbers.amount(totals.ultimate.get("paid")),
                "ult_incurred": numbers.amount(totals.ultimate.get("incurred")),
                "ult_selected": numbers.amount(reserve.ultimate),
                "ibnr_selected": numbers.amount(reserve.ibnr),
                "diagnostics": len(group.diagnostics),
            }
        )
        ids = dict.fromkeys(
            [
                *(f"{kind}_{m}" for kind in ("heatmap", "factors") for m in MEASURES),
                "methods",
                "range",
            ],
            "",
        )
        for measure in MEASURES:
            ids[f"heatmap_{measure}"] = f"{anchor}-heatmap-{measure}"
            figures[ids[f"heatmap_{measure}"]] = charts.heatmap(group.triangles[measure], currency)
            factor_figure = charts.factors(group, measure)
            if factor_figure is not None:
                ids[f"factors_{measure}"] = f"{anchor}-factors-{measure}"
                figures[ids[f"factors_{measure}"]] = factor_figure
        method_figure = charts.methods(group, currency)
        if method_figure is not None:
            ids["methods"] = f"{anchor}-methods"
            figures[ids["methods"]] = method_figure
        range_figure = charts.reserve_range(group, currency)
        if range_figure is not None:
            ids["range"] = f"{anchor}-range"
            figures[ids["range"]] = range_figure
        counts = group.triangles["paid"].claim_counts
        thin_cells = int(((counts >= 0) & (counts < THIN_CELL_CLAIMS)).sum())
        lines.append(
            {
                "name": name,
                "segment": group.group[0],
                "anchor": anchor,
                "figures": ids,
                "origins": len(group.triangles["paid"].origins),
                "ages": [str(a) for a in group.triangles["paid"].ages],
                "triangles": {
                    m: [
                        [o, *[numbers.amount(_value(v)) for v in row]]
                        for o, row in zip(
                            group.triangles[m].origins, group.triangles[m].cumulative, strict=True
                        )
                    ]
                    for m in MEASURES
                },
                "methods": group_methods(group),
                "thin_cells": thin_cells,
                "findings": line_findings.get(anchor, []),
                "summary": summary[-1],
            }
        )
    return {
        "basis": basis,
        "currency": currency,
        "summary": summary,
        "lines": lines,
        "selection_measure": SELECTION_MEASURE,
        "footnotes": {
            "summary": t(
                "{currency}, {basis}. Chain ladder {mt02} on paid and incurred triangles "
                "{mt01}; selected ultimate {mt10}; IBNR = ultimate − incurred at the valuation "
                "date {rs02}. Rounded per {cv06}; totals from unrounded values. Rows of "
                "ultimates.csv and lineage.csv (RS02).",
                currency=currency,
                basis=basis,
                mt02=spec("MT02"),
                mt01=spec("MT01"),
                mt10=spec("MT10"),
                rs02=spec("RS02"),
                cv06=spec("CV06"),
            ),
            "heatmaps": t(
                "Cumulative cells by origin and development age, {basis}; paid on its own "
                "one-hue ramp, incurred on another; the further a cell stands from the page "
                "colour, the larger it is ({specs}).",
                basis=basis,
                specs=spec("MT01", "CV04"),
            ),
            "factors": t(
                "Link ratio of every origin (dots) and the factor selected (bar), {specs}; the "
                "tail factor is in the table. Rows of factors.csv.",
                specs=spec("RS01", "MT02"),
            ),
            "methods": t(
                "Ultimate per origin by method on the {measure} triangle ({specs}), and the "
                "selected ultimate (diamond, {mt10}). The spread between methods shows how much "
                "the answer depends on the method; it is not a confidence interval.",
                measure=t(SELECTION_MEASURE),
                specs=spec("MT02", "MT03", "MT04", "MT05"),
                mt10=spec("MT10"),
            ),
            "range": t(
                "Selected reserve (diamond) with the 25th to 75th percentile (dark bar) and the "
                "5th to 95th percentile (light bar); the Mack coefficient of variation applied "
                "to the selected reserve, lognormal approximation ({specs}). The upper "
                "percentiles are in the table.",
                specs=spec("MT06", "RS03"),
            ),
        },
    }


# --- what did not run, appendices ----------------------------------------------------


def _not_run(r: ReportInputs) -> dict[str, Any]:
    modules = []
    for outcome in r.analysis.modules:
        if outcome.state is ModuleState.RAN:
            continue
        spec = r.catalogue.modules.get(outcome.module)
        modules.append(
            {
                "module": f"{outcome.module} {module_title(r.catalogue, outcome)}",
                "state": t(outcome.state.value),
                "why": [t(x) for x in outcome.reasons],
                "load": t(spec.skip_reason)
                if spec and outcome.state is ModuleState.SKIPPED
                else "",
                "missing": [f"{m.measure}: {m.reason}" for m in outcome.unavailable],
            }
        )
    return {"modules": modules}


def _methods_appendix(r: ReportInputs, spec: _Specs) -> list[dict[str, Any]]:
    used = {s.id for s in r.specs}
    out = []
    for method in sorted(r.catalogue.methods.values(), key=lambda m: m.id):
        if method.id not in used:
            continue
        out.append(
            {
                "id": method.id,
                "spec": spec(method.id),
                "title": method.title_tr
                if language.current() == language.TURKISH
                else method.title_en,
                "plain": " ".join(method.definition.split()),
                "assumptions": [" ".join(a.statement.split()) for a in method.assumptions],
                "parameters": [
                    {"name": p.name, "default": "" if p.default is None else str(p.default)}
                    for p in method.parameters
                ],
            }
        )
    return out


def _assumptions(entries: list[Assumption]) -> dict[str, Any]:
    rows = assumption_rows(entries)
    by_who: dict[str, int] = defaultdict(int)
    by_kind: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        by_who[row["who"] or t("default")] += 1
        by_kind[(row["method"], row["name"])] += 1
    return {
        "total": len(rows),
        "by_who": [{"who": k, "entries": v} for k, v in sorted(by_who.items())],
        "by_kind": [
            {"method": m, "name": t(n.replace("_", " ")), "entries": v}
            for (m, n), v in sorted(by_kind.items())
        ],
        "judgements": [row for row in rows if row["who"] != "default"],
    }


def _lineage_summary(r: ReportInputs) -> dict[str, Any]:
    measures = sorted({x.measure for x in r.analysis.results() if x.available})
    traced = sorted({x.measure for x in r.analysis.results() if x.available and x.concepts})
    return {
        "measures": len(measures),
        "traced": traced,
        "untraced": [m for m in measures if m not in traced],
        **{k: int(v) for k, v in r.lineage.items()},
    }


def _spec_title(catalogue: SpecCatalogue, spec_id: str, english: str) -> str:
    """A specification's title in the language of the report (every specification has both)."""
    found = next((f.spec for f in catalogue.files if f.spec.id == spec_id), None)
    if found is not None and language.current() == language.TURKISH:
        return found.title_tr
    return english


def _reproducibility(r: ReportInputs) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "software": f"{r.metadata.name} {r.package_version}",
        "inputs": [
            {
                "name": i.name,
                "concept": i.concept,
                "size": numbers.count(i.size),
                "sheets": ", ".join(f"{s.name}: {s.rows}" for s in i.sheets),
                "sha256": i.sha256,
            }
            for i in r.inputs
        ],
        "mappings": [
            {
                "file": m.get("file", ""),
                "sheet": m.get("sheet", ""),
                "concept": m.get("concept") or "",
                "source": m.get("source", ""),
                "columns": len(m.get("columns", [])),
            }
            for m in r.mappings
        ],
        "specs": [
            {"id": s.id, "version": s.version, "title": _spec_title(r.catalogue, s.id, s.title)}
            for s in r.specs
        ],
        "settings": _flatten(r.settings),
        "randomness": [
            {"method": str(x.get("method", "")), "seed": str(x.get("seed", ""))}
            for x in r.randomness
        ],
        "outputs": [
            {"name": o.name, "size": numbers.count(o.size), "sha256": o.sha256} for o in r.outputs
        ],
    }


def _flatten(value: Any, prefix: str = "") -> list[dict[str, str]]:
    if isinstance(value, Mapping):
        out: list[dict[str, str]] = []
        for key in sorted(value):
            if key == "assumptions":  # the register has its own appendix
                continue
            out += _flatten(value[key], f"{prefix}.{key}" if prefix else str(key))
        return out
    if isinstance(value, list):
        return [{"name": prefix, "value": ", ".join(str(v) for v in value)}]
    return [{"name": prefix, "value": "" if value is None else str(value)}]


# --- findings -------------------------------------------------------------------------


def scoped_facts(
    reserving: ReservingResult,
    analysis: AnalysisResult,
    quality: QualityReport,
    rates: dict[tuple[str, str], tuple[int, int]],
    titles: Mapping[str, str] | None = None,
    skip_segments: frozenset[str] | None = None,
) -> tuple[dict[str, list[tuple[str, str, Facts]]], dict[str, FactSet]]:
    """The fact sets of every scope as (key, anchor, facts), and the segment facts."""
    currency = shown_currency(reserving.triangles.reporting_currency)
    lines = {line_name(g.group): line_facts(g, rates, currency) for g in reserving.groups}
    premium = segment_premium(analysis)
    ratios = segment_loss_ratios(analysis)
    triangles = reserving.triangles
    comparable = period_complete(
        triangles.cut_off,
        triangles.settings.origin_period,
        triangles.settings.fiscal_year_start_month,
    )
    segments = {
        s: {}
        if skip_segments and s in skip_segments
        else segment_facts(
            s,
            [g for g in reserving.groups if g.group[0] == s],
            premium.get(s, []),
            comparable,
            ratios.get(s, []),
            currency,
        )
        for s in sorted({g.group[0] for g in reserving.groups})
    }
    run = run_facts(reserving, analysis, quality, rates, lines, titles)
    scoped: dict[str, list[tuple[str, str, Facts]]] = {
        "run": [("", "", run)],
        "segment": [(s, "glance", f) for s, f in segments.items()],
        "line": [
            (line_name(g.group), _line_anchor(n), lines[line_name(g.group)])
            for n, g in enumerate(reserving.groups)
        ],
    }
    return scoped, segments


def _finding_rows(found: list[KeyFinding], spec: _Specs) -> list[dict[str, Any]]:
    return [{**f.record(), "evidence": spec(*f.specs)} for f in found]


def build_model(r: ReportInputs) -> dict[str, Any]:
    spec = _Specs(r.catalogue)
    figures: dict[str, Any] = {}
    rates = anomaly_rates(r.anomalies)
    titles = {o.module: module_title(r.catalogue, o) for o in r.analysis.modules}
    mixed = frozenset(
        s
        for s in {g.group[0] for g in r.reserving.groups}
        if mixed_currencies([g for g in r.reserving.groups if g.group[0] == s], r)
    )
    scoped, segment_sets = scoped_facts(r.reserving, r.analysis, r.quality, rates, titles, mixed)
    fired = evaluate(r.catalogue.finding_rules.rules, scoped)
    headline = [f for f in fired if f.scope != "line"]
    line_findings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in fired:
        if f.scope == "line":
            line_findings[f.section].append({**f.record(), "evidence": spec(*f.specs)})
    pages: list[dict[str, Any]] = []
    builders: dict[str, Callable[[], dict[str, Any]]] = {
        "M01": lambda: _data_page(r, spec),
        "M02": lambda: _portfolio_page(r, spec, figures),
        "M03": lambda: _claims_page(r, spec, figures),
        "M05": lambda: _profitability_page(r, spec, figures),
        "M06": lambda: _anomalies_page(r, spec, figures, rates),
    }
    for outcome in r.analysis.modules:
        if outcome.state is ModuleState.SKIPPED or outcome.module not in builders:
            continue
        pages.append(
            {**_module_header(outcome, r.catalogue, spec), "body": builders[outcome.module]()}
        )
    reserving_outcome = next((m for m in r.analysis.modules if m.module == "M04"), None)
    return {
        "language": language.current(),
        "disclaimer": t(" ".join(r.metadata.report.disclaimer.split())),
        "label": t("Indicative — not an official reserve or price"),
        "findings_spec": spec(r.catalogue.finding_rules.id),
        "inflation_spec": spec("MT07"),
        "cover": _cover(r),
        "banners": [f.text for f in fired if f.banner],
        "key_findings": _finding_rows(headline[:KEY_FINDINGS], spec),
        "further_findings": _finding_rows(headline[KEY_FINDINGS:], spec),
        "tiles": _tiles(r, spec, segment_sets),
        "quality_tile": _quality_tile(r, spec),
        "pages": pages,
        "reserving": {
            **(
                _module_header(reserving_outcome, r.catalogue, spec)
                if reserving_outcome is not None
                else {}
            ),
            **_reserving(r, spec, figures, line_findings),
        },
        "not_run": _not_run(r),
        "data_findings": [
            {
                "rule": f.rule,
                "concept": f.concept,
                "severity": f.severity,
                "count": numbers.count(f.count),
                "message": f.message,
                "rows": ", ".join(str(x) for x in f.rows),
            }
            for f in r.data_findings
        ],
        "methods": _methods_appendix(r, spec),
        "assumptions": _assumptions(r.reserving.assumptions()),
        "lineage": _lineage_summary(r),
        "reproducibility": _reproducibility(r),
        "figures": figures,
    }


def earlier_valuation(reserving: ReservingResult) -> date | None:
    """The valuation point before the cut-off on the development grid, if any."""
    points = sorted(
        {
            p
            for t in reserving.triangles.triangles
            for p in t.valuation_points
            if p < reserving.triangles.cut_off
        }
    )
    return points[-1] if points else None


__all__ = ["ReportInputs", "build_model", "earlier_valuation", "scoped_facts"]
