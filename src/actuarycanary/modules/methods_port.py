"""The methods behind the port of the measures (record 0056): RT01, RT02 and AE01 read the
selection (MT10), RS01 to RS03 are the tables of the reserving module.

The port answers on the basis the run was made on only; a measure asked on another basis gets
"not available" with that reason instead of numbers mixed from two bases.
"""

from datetime import date

import numpy as np
import polars as pl

from actuarycanary.measures.port import NotAvailable, Selection
from actuarycanary.methods.assumptions import AssumptionError
from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.mack import PERCENTILES, Mack, applied_to_selected
from actuarycanary.methods.selection import Choice
from actuarycanary.methods.selection import Selection as UltimateSelection
from actuarycanary.modules.reserving import (
    SELECTION_MEASURE,
    GroupReserving,
    ReservingResult,
    earlier_result,
)
from actuarycanary.structures.triangles import MEASURES

IMPLEMENTED = frozenset({"MT03", "MT04", "MT05", "MT06", "MT07", "MT10"})
PERCENTILE_COLUMNS = {0.5: "p50", 0.75: "p75", 0.9: "p90", 0.95: "p95", 0.99: "p99", 0.995: "p99_5"}
SAME_ULTIMATE = 1e-9  # relative: a selected ultimate equal to the Mack one is the Mack one


def selection_of(result: ReservingResult, valuation_date: date) -> Selection | NotAvailable:
    """The MT10 selection as the port hands it to the measures, at the cut-off or recomputed
    at an earlier valuation of the development grid with the same settings and register."""
    source: ReservingResult | None = result
    if valuation_date != result.triangles.cut_off:
        try:
            source = earlier_result(result, valuation_date)
        except AssumptionError as error:
            return NotAvailable(
                f"the register does not fit the triangles at {valuation_date}: {error}"
            )
        if source is None:
            return NotAvailable(f"{valuation_date} is not on the development grid of the triangles")
    assert source is not None
    ultimates: dict[tuple[str, str, str], float] = {}
    expected: dict[tuple[str, str, str], float] = {}
    cdfs: dict[tuple[str, str, str], dict[int, float]] = {}
    for group in source.groups:
        segment, line = group.group
        selected = group.selection
        if isinstance(selected, UltimateSelection):
            fergusons = group.bornhuetter_ferguson[SELECTION_MEASURE]
            for i, origin in enumerate(group.triangles[SELECTION_MEASURE].origins):
                if not np.isfinite(selected.ultimate[i]):
                    continue
                key = (segment, line, origin)
                ultimates[key] = float(selected.ultimate[i])
                by_bf = selected.method[i] is Choice.BORNHUETTER_FERGUSON
                expected[key] = (
                    float(fergusons.prior_ultimate[i])
                    if by_bf and isinstance(fergusons, BornhuetterFerguson)
                    else float(selected.ultimate[i])
                )
        for measure, chain in group.chain_ladder.items():
            if not isinstance(chain, ChainLadder):
                continue
            curve = {
                age: float(chain.cdf[j]) for j, age in enumerate(group.triangles[measure].ages)
            }
            # ages the earlier triangle does not reach are beyond its pattern: the tail factor
            for age in result.triangles.get(measure, group.group).ages:
                curve.setdefault(age, chain.tail_factor)
            cdfs[(measure, segment, line)] = curve
    if not ultimates:
        return NotAvailable("no ultimate could be selected: the chain ladder did not run")
    return Selection(valuation_date, ultimates, cdfs, expected)


class ReservingPort:
    """`MethodsPort` over a reserving result and, when M06 ran, the anomaly methods."""

    def __init__(self, result: ReservingResult, basis: str, extra: frozenset[str] = frozenset()):
        self._result = result
        self._basis = basis
        self._built = IMPLEMENTED | extra
        self._selections: dict[date, Selection | NotAvailable] = {}
        self._tables: dict[str, pl.DataFrame] = {}

    def _wrong_basis(self, asked: str) -> NotAvailable | None:
        if asked and asked != self._basis:
            return NotAvailable(f"the methods ran on the basis {self._basis}, not on {asked}")
        return None

    def selection(self, valuation_date: date, basis: str = "") -> Selection | NotAvailable:
        wrong = self._wrong_basis(basis)
        if wrong:
            return wrong
        if valuation_date not in self._selections:
            self._selections[valuation_date] = selection_of(self._result, valuation_date)
        return self._selections[valuation_date]

    def measure(self, measure_id: str, basis: str = "") -> pl.DataFrame | NotAvailable:
        wrong = self._wrong_basis(basis)
        if wrong:
            return wrong
        if measure_id not in self._tables:
            builders = {"RS01": factors_table, "RS02": ultimates_table, "RS03": range_table}
            if measure_id not in builders:
                return NotAvailable(f"{measure_id} is not a method output")
            self._tables[measure_id] = builders[measure_id](self._result)
        table = self._tables[measure_id]
        if table.height == 0:
            return NotAvailable("no triangle could be developed")
        return table

    def built(self) -> frozenset[str]:
        return self._built


def factors_table(result: ReservingResult) -> pl.DataFrame:
    """RS01 by segment, line, triangle and development column."""
    rows: list[dict[str, object]] = []
    for group in result.groups:
        segment, line = group.group
        for measure in MEASURES:
            chain = group.chain_ladder[measure]
            triangle = group.triangles[measure]
            ages = triangle.ages
            if isinstance(chain, Skipped):
                rows.append(
                    {"segment": segment, "line": line, "measure": measure,
                     "development_period": "", "note": f"chain ladder did not run: {chain.reason}"}
                )  # fmt: skip
                continue
            stability = (
                group.chain_diagnostics[measure].stability
                if measure in group.chain_diagnostics
                else None
            )
            averages = (
                group.chain_diagnostics[measure].averages
                if measure in group.chain_diagnostics
                else {}
            )
            for j in range(len(ages)):
                last = j == len(ages) - 1
                row: dict[str, object] = {
                    "segment": segment,
                    "line": line,
                    "measure": measure,
                    "development_period": f"{ages[j]}-ult" if last else f"{ages[j]}-{ages[j + 1]}",
                    "from_age": float(ages[j]),
                    "selected_factor": chain.tail_factor if last else float(chain.factors[j]),
                    "cdf": float(chain.cdf[j]),
                    "note": "tail factor" if last else "",
                }
                if not last:
                    row["average"] = float(chain.averages[j])
                    for name, values in averages.items():
                        row[name] = float(values[j])
                    if stability is not None:
                        row["link_ratios_used"] = float(stability.used[j])
                        row["link_ratio_min"] = float(stability.minimum[j])
                        row["link_ratio_max"] = float(stability.maximum[j])
                    if chain.overridden[j]:
                        row["note"] = "selected factor replaces the average (assumptions register)"
                rows.append(row)
    return _tidy(rows, ("segment", "line", "measure", "development_period"))


def _tidy(rows: list[dict[str, object]], text: tuple[str, ...]) -> pl.DataFrame:
    """A frame from rows that may lack some columns; text columns first, `note` last."""
    if not rows:
        return pl.DataFrame()
    columns: list[str] = []
    for row in rows:
        columns += [c for c in row if c not in columns]
    numbers = [c for c in columns if c not in text and c != "note"]
    frame = pl.DataFrame(
        [{c: row.get(c) for c in columns} for row in rows],
        schema={
            **{c: pl.String for c in text},
            **{c: pl.Float64 for c in numbers},
            "note": pl.String,
        },
        infer_schema_length=None,
    )
    return frame.with_columns(pl.col("note").fill_null("")).select(*text, *numbers, "note")


def _estimate_row(
    group: GroupReserving,
    origin: str,
    method: str,
    measure: str,
    ultimate: float | None,
    paid: float,
    incurred: float,
    note: str = "",
) -> dict[str, object]:
    known = ultimate is not None and np.isfinite(ultimate)
    return {
        "segment": group.group[0],
        "line": group.group[1],
        "origin_period": origin,
        "method": method,
        "measure": measure,
        "paid": paid,
        "incurred": incurred,
        "ultimate": float(ultimate) if known and ultimate is not None else None,
        "unpaid": float(ultimate - paid) if known and ultimate is not None else None,
        "ibnr": float(ultimate - incurred) if known and ultimate is not None else None,
        "note": note,
    }


def ultimates_table(result: ReservingResult) -> pl.DataFrame:
    """RS02 by segment, line, origin and method; a method that did not run keeps its reason."""
    rows: list[dict[str, object]] = []
    for group in result.groups:
        origins = group.triangles["paid"].origins
        paid, incurred = group.triangles["paid"].latest, group.triangles["incurred"].latest
        for measure in MEASURES:
            for name, results in (
                ("chain_ladder", group.chain_ladder),
                ("bornhuetter_ferguson", group.bornhuetter_ferguson),
                ("cape_cod", group.cape_cod),
                ("expected_loss_ratio", group.expected_loss_ratio),
            ):
                outcome = results.get(measure)
                for i, origin in enumerate(origins):
                    note, value = "", None
                    if isinstance(outcome, Skipped):
                        note = outcome.reason
                    elif outcome is not None:
                        value = float(outcome.ultimate[i])
                        not_run = getattr(outcome, "not_run", {})
                        note = not_run.get(i, "")
                    rows.append(
                        _estimate_row(
                            group,
                            origin,
                            name,
                            measure,
                            value,
                            float(paid[i]),
                            float(incurred[i]),
                            note,
                        )
                    )
        rows += _inflation_rows(group, origins)
        selection = group.selection
        for i, origin in enumerate(origins):
            if isinstance(selection, UltimateSelection):
                note = f"{selection.method[i].value}: {selection.why[i]}"
                value = float(selection.ultimate[i])
            else:
                note = selection.reason if isinstance(selection, Skipped) else ""
                value = None
            rows.append(
                _estimate_row(
                    group,
                    origin,
                    "selected",
                    SELECTION_MEASURE,
                    value,
                    float(paid[i]),
                    float(incurred[i]),
                    note,
                )
            )
    return _tidy(rows, ("segment", "line", "origin_period", "method", "measure"))


def _inflation_rows(group: GroupReserving, origins: tuple[str, ...]) -> list[dict[str, object]]:
    """MT07 rows: amounts at value-date prices, or nominal with a future inflation; the
    incurred at those prices is not built, so there is no IBNR."""
    method = "inflation_adjusted_chain_ladder"
    outcome = group.inflation_adjusted
    if outcome is None:
        return []
    rows: list[dict[str, object]] = []
    paid = group.triangles["paid"].latest
    incurred = group.triangles["incurred"].latest
    for i, origin in enumerate(origins):
        base = {
            "segment": group.group[0],
            "line": group.group[1],
            "origin_period": origin,
            "method": method,
            "measure": "paid",
        }
        if isinstance(outcome, Skipped):
            rows.append(
                {
                    **base,
                    "paid": float(paid[i]),
                    "incurred": float(incurred[i]),
                    "note": outcome.reason,
                }
            )
            continue
        if origin not in group.inflation_adjusted_origins:
            rows.append({**base, "note": "origin not in the inflation-adjusted triangle"})
            continue
        k = group.inflation_adjusted_origins.index(origin)
        nominal = outcome.nominal_ultimate
        if nominal is not None:
            ultimate, unpaid = float(nominal[k]), float(outcome.nominal_unpaid[k])  # type: ignore[index]
            note = f"nominal with future inflation {outcome.future_inflation:g} a year"
            paid_value = float(outcome.nominal_paid[k])
        else:
            ultimate = float(outcome.chain.ultimate[k])
            unpaid = float(outcome.unpaid_at_value_date_prices[k])
            note = f"at value-date prices {outcome.value_date.isoformat()}"
            paid_value = float(outcome.chain.latest[k])
        rows.append(
            {**base, "paid": paid_value, "ultimate": ultimate, "unpaid": unpaid, "note": note}
        )
    return rows


def range_table(result: ReservingResult) -> pl.DataFrame:
    """RS03: Mack standard error, coefficient of variation and the lognormal range of the
    selected reserve, per origin and in total, for the paid and the incurred triangle."""
    rows: list[dict[str, object]] = []
    for group in result.groups:
        selection = group.selection
        origins = group.triangles["paid"].origins
        for measure in MEASURES:
            fitted = group.mack.get(measure)
            base = {"segment": group.group[0], "line": group.group[1], "measure": measure}
            if not isinstance(fitted, Mack):
                reason = fitted.reason if isinstance(fitted, Skipped) else "Mack did not run"
                rows.append(
                    {**base, "origin_period": "Total", "note": f"MT06 did not run: {reason}"}
                )
                continue
            latest = group.triangles[measure].latest
            if isinstance(selection, UltimateSelection):
                reserve = selection.ultimate - latest
                same = np.allclose(
                    selection.ultimate, fitted.chain.ultimate, rtol=SAME_ULTIMATE, atol=0
                )
            else:
                reserve, same = fitted.reserve, True
            label = (
                "Mack" if same else "Mack coefficient of variation applied to the selected reserve"
            )
            origin_cv = fitted.coefficient_of_variation
            parts = [
                (
                    origin,
                    float(fitted.reserve[i]),
                    float(fitted.standard_error[i]),
                    float(origin_cv[i]),
                    float(reserve[i]),
                )
                for i, origin in enumerate(origins)
            ]
            parts.append(
                (
                    "Total",
                    fitted.total_reserve,
                    fitted.total_standard_error,
                    fitted.total_coefficient_of_variation,
                    float(np.nansum(reserve)),
                )
            )
            for origin, mack_reserve, se, cv, selected_reserve in parts:
                applied = applied_to_selected(cv, selected_reserve)
                row: dict[str, object] = {
                    **base,
                    "origin_period": origin,
                    "reserve_mack": mack_reserve,
                    "standard_error_mack": se,
                    "coefficient_of_variation": cv,
                    "reserve_selected": selected_reserve,
                    "standard_error": applied.standard_error,
                }
                shown = applied.range
                if shown is not None:
                    row |= {
                        PERCENTILE_COLUMNS[p]: v
                        for p, v in shown.percentiles.items()
                        if p in PERCENTILES
                    }
                    row["var_99_5"] = shown.value_at_risk
                    row["tvar_99"] = shown.tail_value_at_risk
                    row["note"] = f"{label}; {shown.label}"
                else:
                    row["note"] = (
                        f"{label}; range not shown: the reserve is not positive or the "
                        "standard error is zero"
                    )
                rows.append(row)
    return _tidy(rows, ("segment", "line", "origin_period", "measure"))


__all__ = ["ReservingPort", "factors_table", "range_table", "selection_of", "ultimates_table"]
