"""The M09 page (expenses) and the facts of its finding rules (RP01 1.3.0, record 0388): the
expense and commission ratios of the last twelve months against the twelve before, the ratios
by line, the unit costs (EX04, EX05), the claims-handling ratio (EX03), and the expenses booked
without a line, shown at the level they were booked and never spread."""

import re
from datetime import date
from typing import Any

import polars as pl

from actuarycanary.measures.model import CurrencyView, MeasureResult
from actuarycanary.modules.expenses import AT_VALUE_DATE, NOMINAL, ExpenseTable
from actuarycanary.modules.runner import AnalysisResult
from actuarycanary.report import charts, numbers
from actuarycanary.report.facts import FactSet, _put
from actuarycanary.report.language import t
from actuarycanary.structures.periods import Period, month_index

BY_PERIOD = ("calendar_period",)
BY_LINE = ("segment", "line", "calendar_period")
WINDOW = 12  # months of the headline and of the comparison before it
RATIOS = (("EX02", "Expense ratio"), ("EX01", "Commission ratio"))
NOT_ALLOCATED = "not allocated"
MISSING_ROWS = "expense rows in"  # the note of a unit cost that a missing month stops


def find_view(
    analysis: AnalysisResult, measure: str, breakdowns: tuple[str, ...], period: Period | None
) -> MeasureResult | None:
    """The available result of a measure view; `period` None takes the first one (the run's)."""
    for r in analysis.results():
        same = r.measure == measure and r.request.breakdowns == breakdowns and r.available
        if same and (period is None or r.request.period is period):
            return r
    return None


def _month_labels(cut_off: date, back: int, count: int = WINDOW) -> list[str]:
    last = month_index(cut_off) - back
    return [f"{m // 12}-{m % 12 + 1:02d}" for m in range(last - count + 1, last + 1)]


def window_ratio(frame: pl.DataFrame, labels: list[str]) -> float | None:
    """Sum of numerators over sum of denominators of the months `labels`; None unless every
    month is there and the denominator is positive."""
    part = frame.filter(pl.col("calendar_period").is_in(labels))
    if part["calendar_period"].n_unique() < len(labels):
        return None
    if part["numerator"].null_count() or part["denominator"].null_count():
        return None
    bottom = float(part["denominator"].sum())
    return float(part["numerator"].sum()) / bottom if bottom > 0 else None


def _windows(result: MeasureResult | None, cut_off: date) -> tuple[float | None, float | None]:
    if result is None or result.frame is None:
        return None, None
    frame = result.frame
    return (
        window_ratio(frame, _month_labels(cut_off, 0)),
        window_ratio(frame, _month_labels(cut_off, WINDOW)),
    )


def _headline(analysis: AnalysisResult, cut_off: date) -> list[dict[str, Any]]:
    rows = []
    for measure, title in RATIOS:
        now, before = _windows(find_view(analysis, measure, BY_PERIOD, Period.MONTH), cut_off)
        change = None if now is None or before is None else now - before
        rows.append(
            {
                "measure": f"{measure} {t(title)}",
                "now": numbers.ratio(now),
                "before": numbers.ratio(before),
                "change": numbers.change_points(change),
            }
        )
    return rows


def _by_line(analysis: AnalysisResult, cut_off: date, figures: dict[str, Any]) -> dict[str, Any]:
    """Per line: both ratios over the last twelve months and the twelve before, and one chart
    of the expense ratio by month with a trace per line."""
    lines: dict[tuple[str, str], dict[str, str]] = {}
    traces: list[dict[str, Any]] = []
    for measure, _ in RATIOS:
        found = find_view(analysis, measure, BY_LINE, Period.MONTH)
        if found is None or found.frame is None:
            continue
        for key, part in found.frame.partition_by(
            ["segment", "line"], as_dict=True, maintain_order=True
        ).items():
            now = window_ratio(part, _month_labels(cut_off, 0))
            before = window_ratio(part, _month_labels(cut_off, WINDOW))
            row = lines.setdefault((str(key[0]), str(key[1])), {})
            row[f"{measure}_now"] = numbers.ratio(now)
            row[f"{measure}_before"] = numbers.ratio(before)
            if measure == "EX02":
                shown = part.filter(pl.col("value").is_not_null()).sort("calendar_period")
                if shown.height:
                    traces.append(
                        {
                            "type": "scatter",
                            "mode": "lines",
                            "name": f"{key[0]} · {key[1]}",
                            "x": shown["calendar_period"].to_list(),
                            "y": [round(v, 6) for v in shown["value"].to_list()],
                            "line": {"width": 2},
                            "hovertemplate": "%{fullData.name} %{x}: %{y:.1%}<extra></extra>",
                        }
                    )
    figure_id = ""
    if traces:
        figure_id = "expenses-by-line"
        figures[figure_id] = {
            "data": traces,
            "layout": charts._layout(
                t("Expense ratio by line and month"),
                t("Month"),
                t("Ratio"),
                xaxis={"title": {"text": t("Month")}, "type": "category", "nticks": 12},
                yaxis={"title": {"text": t("Ratio")}, "tickformat": ".0%", "rangemode": "tozero"},
                showlegend=True,
                height=300,
            ),
        }
    empty = numbers.EMPTY
    rows = [
        {
            "line": f"{s} · {name}",
            "expense_now": row.get("EX02_now", empty),
            "expense_before": row.get("EX02_before", empty),
            "commission_now": row.get("EX01_now", empty),
            "commission_before": row.get("EX01_before", empty),
        }
        for (s, name), row in sorted(lines.items())
    ]
    return {"rows": rows, "figure": figure_id}


def _by_line_note(spec: Any) -> str:
    return t(
        "Expense ratio {ex02} by line and month, over the earned premium of the line {pr02}; "
        "only expenses booked with a line are in a line.",
        ex02=spec("EX02"),
        pr02=spec("PR02"),
    )


def _by_period(result: MeasureResult | None, show: Any) -> dict[str, dict[str, str]]:
    if result is None or result.frame is None or "currency" in result.frame.columns:
        return {}
    return {
        str(r["calendar_period"]): {"value": show(r["value"]), "note": _note(r["note"] or "")}
        for r in result.frame.iter_rows(named=True)
    }


_GAP = re.compile(r"^no (.+) expense rows in (.+): not computed$")
_FIXED_NOTES = (
    "first period of the file: the open count at its start is unknown",
    "no policies in force in the period: not computed",
    "no claims handled in the period: not computed",
)


def _note(note: str) -> str:
    """The note of a unit cost in the language of the report: the fixed notes of EX04 and EX05,
    and the months without expense rows."""
    if note in _FIXED_NOTES:
        return t(note)
    gap = _GAP.match(note)
    if gap:
        return t("no expense rows in {months}: not computed", months=gap[2])
    return note


def _unit_costs(analysis: AnalysisResult) -> list[dict[str, Any]]:
    per_policy = _by_period(find_view(analysis, "EX04", BY_PERIOD, None), numbers.amount)
    per_claim = _by_period(find_view(analysis, "EX05", BY_PERIOD, None), numbers.amount)
    handling = _by_period(find_view(analysis, "EX03", BY_PERIOD, None), numbers.ratio)
    empty = {"value": numbers.EMPTY, "note": ""}
    rows = []
    for period in sorted(set(per_policy) | set(per_claim) | set(handling)):
        a, b, c = (x.get(period, empty) for x in (per_policy, per_claim, handling))
        notes = [f"{m}: {x['note']}" for m, x in (("EX04", a), ("EX05", b)) if x["note"]]
        rows.append(
            {
                "period": period,
                "per_policy": a["value"],
                "per_claim": b["value"],
                "handling": c["value"],
                "note": "; ".join(notes),
            }
        )
    return rows


def _unallocated(table: ExpenseTable | None) -> list[dict[str, Any]]:
    """Expenses booked without a line, by year, type and the level they carry."""
    if table is None or table.unallocated.height == 0:
        return []
    level = (
        pl.when(pl.col("segment").is_not_null())
        .then(pl.format("{} {}", pl.lit(t("segment")), "segment"))
        .when(pl.col("entity").is_not_null())
        .then(pl.format("{} {}", pl.lit(t("entity")), "entity"))
        .otherwise(pl.lit(t(NOT_ALLOCATED)))
    )
    grouped = (
        table.unallocated.with_columns(
            level.alias("_level"), pl.col("month").dt.year().alias("_year")
        )
        .group_by("_year", "type", "_level", "currency")
        .agg(pl.col(NOMINAL).sum(), pl.col(AT_VALUE_DATE).sum(), pl.col("rows").sum())
        .sort("_year", "type", "_level", "currency")
    )
    return [
        {
            "year": str(r["_year"]),
            "type": r["type"],
            "level": r["_level"],
            "currency": r["currency"],
            "rows": numbers.count(r["rows"]),
            "amount": numbers.amount(r[NOMINAL]),
            "priced": numbers.amount(r[AT_VALUE_DATE]),
        }
        for r in grouped.iter_rows(named=True)
    ]


def expenses_page(
    analysis: AnalysisResult,
    table: ExpenseTable | None,
    cut_off: date,
    spec: Any,
    figures: dict[str, Any],
    currency: str,
) -> dict[str, Any]:
    priced = table is not None and table.frame[AT_VALUE_DATE].null_count() < table.frame.height
    unit = find_view(analysis, "EX04", BY_PERIOD, None) or find_view(
        analysis, "EX05", BY_PERIOD, None
    )
    return {
        "headline": _headline(analysis, cut_off),
        "by_line": {**_by_line(analysis, cut_off, figures), "note": _by_line_note(spec)},
        "unit_costs": _unit_costs(analysis),
        "unit_basis": charts_basis(unit),
        "unallocated": _unallocated(table),
        "priced": priced,
        "notes": list(table.notes) if table is not None else [],
        "footnote": t(
            "{currency}. Expense ratio {ex02} and commission ratio {ex01} over earned premium, "
            "the last twelve months to the cut-off against the twelve before; administration "
            "cost per policy in force {ex04}, claims-handling cost per claim handled {ex05}, "
            "claims-handling ratio {ex03}. A period with a month without expense rows is not "
            "computed. File: expenses_by_period.csv.",
            currency=currency,
            ex02=spec("EX02"),
            ex01=spec("EX01"),
            ex04=spec("EX04"),
            ex05=spec("EX05"),
            ex03=spec("EX03"),
        ),
    }


def charts_basis(result: MeasureResult | None) -> str:
    """The basis of the unit costs in the language of the report."""
    if result is None:
        return ""
    return ", ".join(t(part) for part in result.request.basis.label().split(", "))


def add_expense_facts(
    facts: FactSet, analysis: AnalysisResult, table: ExpenseTable | None, cut_off: date
) -> None:
    """Facts of KF38 to KF41: both ratios over the last twelve months and the twelve before,
    the share of the expenses of the last twelve months booked without a line, and the periods
    whose unit cost a month without expense rows stops."""
    for measure, name in (("EX02", "expense_ratio"), ("EX01", "commission_ratio")):
        result = find_view(analysis, measure, BY_PERIOD, Period.MONTH)
        if result is not None and result.request.basis.currency is not CurrencyView.REPORTING:
            continue
        now, before = _windows(result, cut_off)
        if now is None or before is None:
            continue
        _put(facts, f"{name}_12m", now, "ratio")
        _put(facts, f"{name}_previous", before, "ratio")
        _put(facts, f"{name}_change_size", abs(now - before), "ratio")
    if table is not None and table.frame.height and table.frame["currency"].n_unique() == 1:
        window = table.frame.filter(
            (month_of_date("month") > month_index(cut_off) - WINDOW) & (pl.col("month") <= cut_off)
        )
        total = float(window[NOMINAL].sum())
        loose = float(window.filter(pl.col("line").is_null())[NOMINAL].sum())
        if total > 0:
            _put(facts, "unallocated_expenses", loose, "amount")
            _put(facts, "unallocated_expense_share", loose / total, "ratio")
    periods: set[str] = set()
    stopped: set[str] = set()
    for measure in ("EX04", "EX05"):
        result = find_view(analysis, measure, BY_PERIOD, None)
        if result is None or result.frame is None:
            continue
        for r in result.frame.iter_rows(named=True):
            periods.add(str(r["calendar_period"]))
            if MISSING_ROWS in (r["note"] or ""):
                stopped.add(str(r["calendar_period"]))
    if periods:
        _put(facts, "unit_cost_periods", float(len(periods)), "count")
        _put(facts, "unit_cost_periods_missing", float(len(stopped)), "count")


def month_of_date(column: str) -> pl.Expr:
    return pl.col(column).dt.year().cast(pl.Int64) * 12 + pl.col(column).dt.month() - 1
