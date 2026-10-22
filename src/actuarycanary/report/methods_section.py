"""Plain tables of the reserving methods for one group of the report: ultimates by method,
Mack standard errors, the inflation-adjusted chain ladder, factor stability and diagnostics.

Data and tables only; the executive report that organises them is a later item. Rounding is
CV06 (`report.numbers`); the files `ultimates.csv`, `reserve_range.csv`, `cash_flows.csv`,
`diagnostics.csv` and `assumptions.csv` hold the unrounded values.
"""

from typing import Any

import numpy as np

from actuarycanary.methods.assumptions import Assumption
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.inflation_adjusted import InflationAdjusted
from actuarycanary.methods.mack import Mack, applied_to_selected
from actuarycanary.methods.selection import Selection
from actuarycanary.modules.reserving import SELECTION_MEASURE, GroupReserving
from actuarycanary.report import numbers
from actuarycanary.structures.triangles import MEASURES

METHOD_LABELS = (
    ("chain_ladder", "Chain ladder"),
    ("bornhuetter_ferguson", "Bornhuetter–Ferguson"),
    ("cape_cod", "Cape Cod"),
    ("expected_loss_ratio", "Expected loss ratio"),
)
PERCENTILES = (0.75, 0.95, 0.995)
RANGE_LABEL = "lognormal approximation with the Mack mean and standard error"


def _ultimates(group: GroupReserving) -> dict[str, Any]:
    origins = group.triangles["paid"].origins
    columns: list[tuple[str, np.ndarray]] = []
    for measure in MEASURES:
        for key, label in METHOD_LABELS:
            found = group.method_ultimates(measure).get(key)
            if found is not None:
                columns.append((f"{label}, {measure}", found))
    adjusted = group.inflation_adjusted
    if isinstance(adjusted, InflationAdjusted):
        by_origin = dict(
            zip(group.inflation_adjusted_origins, adjusted.chain.ultimate, strict=True)
        )
        mapped = np.array([by_origin.get(o, np.nan) for o in origins])
        columns.append(("Inflation-adjusted chain ladder, paid, value-date prices", mapped))
    selection = group.selection
    selected = (
        selection.ultimate if isinstance(selection, Selection) else np.full(len(origins), np.nan)
    )
    rows = []
    for i, origin in enumerate(origins):
        chosen = (
            selection.method[i].value.replace("_", " ") if isinstance(selection, Selection) else ""
        )
        rows.append(
            {
                "origin": origin,
                "cells": [numbers.amount(float(v[i])) for _, v in columns],
                "selected": numbers.amount(float(selected[i])),
                "chosen": chosen,
                "why": selection.why[i] if isinstance(selection, Selection) else "",
                "total": False,
            }
        )
    total = {
        "origin": "Total",
        "cells": [numbers.amount(_total(v)) for _, v in columns],
        "selected": numbers.amount(_total(selected)),
        "chosen": "",
        "why": "",
        "total": True,
    }
    return {"headers": [name for name, _ in columns], "rows": [*rows, total]}


def _total(values: np.ndarray) -> float | None:
    """Sum over the origins, None when an origin has no value (a partial sum would mislead)."""
    return float(values.sum()) if np.isfinite(values).all() else None


def _not_run(group: GroupReserving) -> list[str]:
    """Why a method has no result, and the origins it left out."""
    notes: list[str] = []
    titles = {
        "bornhuetter_ferguson": "Bornhuetter–Ferguson (MT03)",
        "cape_cod": "Cape Cod (MT04)",
        "expected_loss_ratio": "Expected loss ratio (MT05)",
    }
    for key, title in titles.items():
        for measure in MEASURES:
            result = getattr(group, key).get(measure)
            if isinstance(result, Skipped):
                notes.append(f"{title} on {measure} did not run: {result.reason}.")
            elif result is not None and result.not_run:
                origins = group.triangles[measure].origins
                left = "; ".join(f"{origins[i]} ({r})" for i, r in result.not_run.items())
                notes.append(f"{title} on {measure} left out: {left}.")
    for measure in MEASURES:
        found = group.mack.get(measure)
        if isinstance(found, Skipped):
            notes.append(f"Mack standard error (MT06) on {measure} did not run: {found.reason}.")
    adjusted = group.inflation_adjusted
    if isinstance(adjusted, Skipped):
        notes.append(f"Inflation-adjusted chain ladder (MT07) did not run: {adjusted.reason}.")
    if isinstance(group.selection, Skipped):
        notes.append(f"Selection (MT10) did not run: {group.selection.reason}.")
    return notes


def _mack(group: GroupReserving) -> dict[str, Any] | None:
    fitted = {m: group.mack.get(m) for m in MEASURES}
    if not any(isinstance(f, Mack) for f in fitted.values()):
        return None
    origins = group.triangles["paid"].origins
    rows: list[dict[str, Any]] = []
    for i, origin in enumerate([*origins, "Total"]):
        total = origin == "Total"
        cells: list[str] = []
        for measure in MEASURES:
            f = fitted[measure]
            if not isinstance(f, Mack):
                cells += [numbers.EMPTY] * 3
                continue
            reserve = f.total_reserve if total else float(f.reserve[i])
            se = f.total_standard_error if total else float(f.standard_error[i])
            cv = f.total_coefficient_of_variation if total else float(f.coefficient_of_variation[i])
            cells += [numbers.amount(reserve), numbers.amount(se), numbers.ratio(cv)]
        rows.append({"origin": origin, "cells": cells, "total": total})
    ranges: list[dict[str, Any]] = []
    for measure in MEASURES:
        f = fitted[measure]
        if not isinstance(f, Mack):
            continue
        selection = group.selection
        latest = group.triangles[measure].latest
        reserve = (
            float(np.nansum(selection.ultimate - latest))
            if isinstance(selection, Selection)
            else f.total_reserve
        )
        shown = applied_to_selected(f.total_coefficient_of_variation, reserve)
        if shown.range is None:
            ranges.append({"measure": measure, "reserve": numbers.amount(reserve), "cells": []})
            continue
        ranges.append(
            {
                "measure": measure,
                "reserve": numbers.amount(reserve),
                "cells": [numbers.amount(shown.range.percentiles[p]) for p in PERCENTILES]
                + [
                    numbers.amount(shown.range.value_at_risk),
                    numbers.amount(shown.range.tail_value_at_risk),
                ],
            }
        )
    return {"rows": rows, "ranges": ranges, "label": RANGE_LABEL}


def _inflation(group: GroupReserving) -> dict[str, Any] | None:
    found = group.inflation_adjusted
    if not isinstance(found, InflationAdjusted):
        return None
    paid_nominal = found.nominal_paid
    nominal_ultimate, nominal_unpaid = found.nominal_ultimate, found.nominal_unpaid
    rows = []
    for k, origin in enumerate(group.inflation_adjusted_origins):
        rows.append(
            {
                "origin": origin,
                "cells": [
                    numbers.amount(float(found.chain.latest[k])),
                    numbers.amount(float(found.chain.ultimate[k])),
                    numbers.amount(float(found.unpaid_at_value_date_prices[k])),
                    numbers.amount(float(paid_nominal[k])),
                    numbers.amount(
                        None if nominal_ultimate is None else float(nominal_ultimate[k])
                    ),
                    numbers.amount(None if nominal_unpaid is None else float(nominal_unpaid[k])),
                ],
            }
        )
    return {
        "rows": rows,
        "value_date": found.value_date.isoformat(),
        "future_inflation": None
        if found.future_inflation is None
        else f"{found.future_inflation:g}",
    }


def _stability(group: GroupReserving) -> list[dict[str, Any]]:
    tables = []
    for measure in MEASURES:
        found = group.chain_diagnostics.get(measure)
        if found is None:
            continue
        s = found.stability
        averages = found.averages
        rows = []
        for j, column in enumerate(s.columns):
            rows.append(
                {
                    "column": column,
                    "cells": [
                        f"{int(s.used[j])}",
                        numbers.factor(float(s.minimum[j])),
                        numbers.factor(float(s.maximum[j])),
                        numbers.factor(float(s.coefficient_of_variation[j])),
                        *[numbers.factor(float(v[j])) for v in averages.values()],
                        numbers.factor(float(s.selected[j])),
                    ],
                }
            )
        tables.append(
            {"measure": measure, "names": [n.replace("_", " ") for n in averages], "rows": rows}
        )
    return tables


def _diagnostics(group: GroupReserving) -> list[dict[str, str]]:
    return [
        {
            "measure": d.measure or "all",
            "method": d.item.method,
            "code": d.item.code.replace("_", " ").lower(),
            "target": d.item.target,
            "message": d.item.message,
        }
        for d in group.diagnostics
    ]


def group_methods(group: GroupReserving) -> dict[str, Any]:
    return {
        "ultimates": _ultimates(group),
        "not_run": _not_run(group),
        "mack": _mack(group),
        "inflation": _inflation(group),
        "stability": _stability(group),
        "diagnostics": _diagnostics(group),
        "selection_measure": SELECTION_MEASURE,
    }


def assumption_rows(entries: list[Assumption]) -> list[dict[str, str]]:
    def text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    return [
        {
            "method": e.method,
            "name": e.name,
            "scope": e.scope,
            "target": e.target,
            "value": text(e.value),
            "default": text(e.default),
            "who": e.who,
            "when": e.when.isoformat() if e.when else "",
            "why": e.why,
        }
        for e in entries
    ]


__all__ = ["assumption_rows", "group_methods"]
