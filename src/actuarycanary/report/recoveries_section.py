"""The M07 page (recoveries) and the facts of its finding rules (RP01 1.3.0, record 0388):
recovered to date by type, recovery ratios by origin (RC01, RC02), the recovery development
triangle (RC04), the delay from first payment to recovery (RC03), and the source of the figures
with the reconciliation of transactions and to-date fields."""

import math
from collections import defaultdict
from typing import Any

import polars as pl

from actuarycanary.measures.model import CurrencyView, MeasureResult
from actuarycanary.measures.recovery_measures import TOTAL
from actuarycanary.modules.recoveries import (
    NOT_RECONCILED_DERIVED,
    NOT_RECONCILED_NO_FIELDS,
    RecoveryTables,
)
from actuarycanary.modules.runner import AnalysisResult
from actuarycanary.report import charts, numbers
from actuarycanary.report.facts import FactSet, _put, find_result
from actuarycanary.report.language import t

DEVELOPMENT_VIEW = ("segment", "line", "recovery_type", "origin_period", "development_period")
BY_ORIGIN = ("segment", "line", "origin_period")
RECONCILIATION_ROWS = 10  # differences listed on the page; all are in the output file
TYPE_LABELS = {
    "RECOVERY_SUBROGATION": "Subrogation",
    "RECOVERY_SALVAGE": "Salvage",
    "RECOVERY_OTHER": "Other recoveries",
    TOTAL: "All recoveries",
}
NOT_RECONCILED = (NOT_RECONCILED_DERIVED, NOT_RECONCILED_NO_FIELDS)
SOURCE_LABELS = {
    "transactions": "recovery transactions",
    "derived": "derived from the to-date fields of claim valuations",
}


def _type_label(kind: object) -> str:
    """A recovery type in the language of the report; a type without a label is shown as is."""
    known = TYPE_LABELS.get(str(kind))
    return t(known) if known else str(kind)


def _cells(result: MeasureResult | None) -> pl.DataFrame:
    """The RC04 cells with the age as a number and the latest cell of each origin marked."""
    if result is None or result.frame is None or result.frame.height == 0:
        return pl.DataFrame()
    frame = result.frame.with_columns(pl.col("development_period").cast(pl.Int64).alias("age"))
    return frame.with_columns(
        (pl.col("age") == pl.col("age").max().over("segment", "line", "origin_period")).alias(
            "latest"
        )
    )


def _summed(cells: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    return cells.group_by(by, maintain_order=True).agg(
        pl.col("numerator").sum(), pl.col("denominator").sum()
    )


def _share(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _headline(cells: pl.DataFrame) -> list[dict[str, Any]]:
    """Per type: recovered to date and as a share of paid, and what the last development
    period added against the one before (the diagonal before the latest, and the one before)."""
    rows = []
    back = cells.with_columns(
        pl.col("age")
        .rank("dense", descending=True)
        .over("segment", "line", "origin_period")
        .alias("step")
    )
    for kind in dict.fromkeys(cells["recovery_type"].to_list()):
        of_kind = back.filter(pl.col("recovery_type") == kind)
        level = {
            step: float(of_kind.filter(pl.col("step") == step)["numerator"].sum())
            for step in (1, 2, 3)
        }
        paid = float(of_kind.filter(pl.col("step") == 1)["denominator"].sum())
        last, before = level[1] - level[2], level[2] - level[3]
        rows.append(
            {
                "type": _type_label(kind),
                "recovered": numbers.amount(level[1]),
                "share": numbers.ratio(_share(level[1], paid)),
                "last": numbers.amount(last),
                "before": numbers.amount(before),
                "change": numbers.change_amount(last - before),
            }
        )
    return rows


def _triangle_figure(cells: pl.DataFrame, kind: str) -> dict[str, Any] | None:
    """All lines together for one recovery type: cumulative recoveries over cumulative paid by
    origin and development age."""
    part = _summed(cells.filter(pl.col("recovery_type") == kind), ["origin_period", "age"]).sort(
        "origin_period", "age"
    )
    if part.height == 0 or float(part["numerator"].sum()) == 0:
        return None
    origins = list(dict.fromkeys(part["origin_period"].to_list()))
    ages = sorted(set(part["age"].to_list()))
    found = {(r["origin_period"], r["age"]): r for r in part.iter_rows(named=True)}
    z, text = [], []
    for origin in origins:
        z_row, text_row = [], []
        for age in ages:
            cell = found.get((origin, age))
            value = None if cell is None else _share(cell["numerator"], cell["denominator"])
            z_row.append(None if value is None else round(value, 6))
            text_row.append(
                ""
                if cell is None
                else t(
                    "{ratio} · recovered {recovered} of paid {paid}",
                    ratio=numbers.ratio(value),
                    recovered=numbers.amount(cell["numerator"]),
                    paid=numbers.amount(cell["denominator"]),
                )
            )
        z.append(z_row)
        text.append(text_row)
    title = t("Recoveries over paid, {type}", type=_type_label(kind))
    return {
        "data": [
            {
                "type": "heatmap",
                "x": [str(a) for a in ages],
                "y": origins,
                "z": z,
                "text": text,
                "hovertemplate": t("Origin %{y} · age %{x} months<br>%{text}<extra></extra>"),
                "xgap": 2,
                "ygap": 2,
                "showscale": False,
                "colorscale": "ramp:paid",
            }
        ],
        "layout": charts._layout(
            title,
            t("Development age (months)"),
            t("Origin"),
            xaxis={"title": {"text": t("Development age (months)")}, "type": "category"},
            yaxis={"title": {"text": t("Origin")}, "type": "category", "autorange": "reversed"},
            height=260,
        ),
    }


def _by_origin(analysis: AnalysisResult, cells: pl.DataFrame) -> list[dict[str, Any]]:
    """Per line: the recovery ratios of each origin with its development age (RC01, RC02) and
    the total of RC04 at the latest diagonal."""
    ratios: dict[tuple[str, str, str], dict[str, float | None]] = defaultdict(dict)
    for measure in ("RC01", "RC02"):
        found = find_result(analysis, measure, BY_ORIGIN)
        if found is None or found.frame is None:
            continue
        for r in found.frame.iter_rows(named=True):
            ratios[(r["segment"], r["line"], str(r["origin_period"]))][measure] = r["value"]
    at_latest = (
        cells.filter(pl.col("latest") & (pl.col("recovery_type") == TOTAL))
        if cells.height
        else cells
    )
    latest = {
        (r["segment"], r["line"], r["origin_period"]): r for r in at_latest.iter_rows(named=True)
    }
    lines: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for key in sorted(set(ratios) | set(latest)):
        cell = latest.get(key)
        lines[key[:2]].append(
            {
                "origin": key[2],
                "age": numbers.count(cell["age"]) if cell else numbers.EMPTY,
                "subrogation": numbers.ratio(ratios.get(key, {}).get("RC01")),
                "salvage": numbers.ratio(ratios.get(key, {}).get("RC02")),
                "total": numbers.ratio(cell["value"] if cell else None),
                "recovered": numbers.amount(cell["numerator"] if cell else None),
            }
        )
    return [{"line": f"{s} · {name}", "rows": rows} for (s, name), rows in lines.items()]


def _delays(analysis: AnalysisResult) -> list[dict[str, Any]]:
    rows = []
    for breakdowns in (("recovery_type",), ("segment", "line", "recovery_type")):
        found = find_result(analysis, "RC03", breakdowns)
        if found is None or found.frame is None:
            continue
        for r in found.frame.iter_rows(named=True):
            line = f"{r['segment']} · {r['line']}" if "line" in r else t("All lines")
            rows.append(
                {
                    "line": line,
                    "type": _type_label(r["recovery_type"]),
                    "n": numbers.count(r["n"]),
                    "mean": numbers.count(r["value"]),
                    "median": numbers.count(r["p50"]),
                    "p90": numbers.count(r["p90"]),
                }
            )
    return rows


def recoveries_page(
    analysis: AnalysisResult,
    tables: RecoveryTables | None,
    spec: Any,
    figures: dict[str, Any],
    currency: str,
) -> dict[str, Any]:
    development = find_result(analysis, "RC04", DEVELOPMENT_VIEW)
    cells = _cells(development)
    one_currency = (
        development is None or development.request.basis.currency is CurrencyView.REPORTING
    )
    charts_shown = []
    if cells.height and one_currency:
        for kind in dict.fromkeys(cells["recovery_type"].to_list()):
            figure = _triangle_figure(cells, kind)
            if figure is not None:
                figure_id = f"recoveries-{kind.lower()}"
                figures[figure_id] = figure
                charts_shown.append({"id": figure_id, "title": figure["layout"]["title"]["text"]})
    reconciliation = []
    differences = 0
    if tables is not None:
        differences = tables.reconciliation.height
        for r in tables.reconciliation.head(RECONCILIATION_ROWS).iter_rows(named=True):
            reconciliation.append(
                {
                    "claim": r["claim_id"],
                    "type": _type_label(r["type"]),
                    "date": str(r["valuation_date"]),
                    "booked": numbers.amount(r["booked"]),
                    "to_date": numbers.amount(r["to_date"]),
                    "difference": numbers.change_amount(r["difference"]),
                }
            )
    source = tables.source if tables is not None else ""
    return {
        "headline": _headline(cells) if cells.height and one_currency else [],
        "figures": charts_shown,
        "lines": _by_origin(analysis, cells),
        "delays": _delays(analysis),
        "source": t(SOURCE_LABELS[source]) if source in SOURCE_LABELS else "",
        "source_note": tables.note if tables is not None else "",
        "reconciliation": reconciliation,
        "differences": numbers.count(differences),
        "compared": numbers.count(tables.compared if tables is not None else 0),
        "reconciliation_note": t(tables.reconciliation_note)
        if tables is not None and tables.reconciliation_note in NOT_RECONCILED
        else "",
        "figure_note": t(
            "Cumulative recoveries over cumulative paid by origin and development age, all "
            "lines together, one chart per recovery type {rc04}; cells of the paid triangle "
            "{mt01}.",
            rc04=spec("RC04"),
            mt01=spec("MT01"),
        ),
        "reconciled": bool(tables is not None and tables.compared),
        "footnote": t(
            "{currency}; cumulative recoveries over cumulative paid by origin and development "
            "age {rc04}, subrogation and salvage ratios {ratios}, delay in days from the month "
            "end of the first payment to the booking {rc03}. Recoveries are outside the "
            "reinsurance basis {cv03}. Files: recoveries.csv, recovery_development.csv, "
            "recovery_reconciliation.csv.",
            currency=currency,
            rc04=spec("RC04"),
            ratios=spec("RC01", "RC02"),
            rc03=spec("RC03"),
            cv03=spec("CV03"),
        ),
    }


def add_recovery_facts(
    facts: FactSet, analysis: AnalysisResult, tables: RecoveryTables | None
) -> None:
    """Facts of KF35 to KF37: recovered to date and its share of paid, the differences of the
    reconciliation, and the latest origin against the earlier ones at the first development
    age. A fact the run cannot compute is absent."""
    if tables is not None and tables.compared:
        _put(facts, "recovery_differences", float(tables.reconciliation.height), "count")
        _put(facts, "recovery_valuations_compared", float(tables.compared), "count")
    development = find_result(analysis, "RC04", DEVELOPMENT_VIEW)
    cells = _cells(development)
    if cells.height == 0 or development is None:
        return
    if development.request.basis.currency is not CurrencyView.REPORTING:
        return  # amounts of several currencies are not added
    total = cells.filter(pl.col("recovery_type") == TOTAL)
    latest = total.filter(pl.col("latest"))
    recovered, paid = float(latest["numerator"].sum()), float(latest["denominator"].sum())
    _put(facts, "recovered_to_date", recovered, "amount")
    _put(facts, "recovery_share", _share(recovered, paid), "ratio")
    if tables is not None and tables.source in SOURCE_LABELS:
        _put(facts, "recovery_source", t(SOURCE_LABELS[tables.source]), "text")
    first_age = int(total["age"].min())  # type: ignore[arg-type]
    by_origin = _summed(total.filter(pl.col("age") == first_age), ["origin_period"]).sort(
        "origin_period"
    )
    if by_origin.height < 3:
        return
    *earlier, last = by_origin.iter_rows(named=True)
    before = _share(sum(r["numerator"] for r in earlier), sum(r["denominator"] for r in earlier))
    now = _share(last["numerator"], last["denominator"])
    if before is None or now is None or before <= 0 or not math.isfinite(before):
        return
    _put(facts, "recovery_first_age", float(first_age), "count")
    _put(facts, "recovery_latest_origin", str(last["origin_period"]), "text")
    _put(facts, "recovery_ratio_latest", now, "ratio")
    _put(facts, "recovery_ratio_earlier", before, "ratio")
    _put(facts, "recovery_ratio_drop", 1 - now / before, "ratio")
