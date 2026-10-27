"""The data files of the reserving and anomaly modules, unrounded (CV06), except the values of the
tier B and severity methods in diagnostics.csv, which carry 10 significant digits (CV06 1.1.0)."""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.manifest.run import round_significant
from actuarycanary.methods.assumptions import Assumption
from actuarycanary.methods.inflation_adjusted import InflationAdjusted, future_cash_flows
from actuarycanary.modules.anomalies import ANOMALY_COLUMNS, AnomalyResult
from actuarycanary.modules.methods_port import range_table, ultimates_table
from actuarycanary.modules.reserving import ReservingResult

# The methods whose rows in diagnostics.csv carry floats to 10 significant digits (CV06 1.1.0)
ROUNDED_METHODS = frozenset(
    ("MT11", "MT12", "MT13", "MT14", "MT15", "MT16", "MT17", "MT18", "MT22", "AE02")
)
ASSUMPTIONS_NAME = "assumptions.csv"
ANOMALIES_NAME = "anomalies.csv"
DIAGNOSTICS_NAME = "diagnostics.csv"
ULTIMATES_NAME = "ultimates.csv"
RANGE_NAME = "reserve_range.csv"
CASH_FLOWS_NAME = "cash_flows.csv"
ASSUMPTION_COLUMNS = ("method", "name", "scope", "target", "value", "default", "who", "when", "why")
DIAGNOSTIC_COLUMNS = (
    "segment",
    "line",
    "measure",
    "method",
    "code",
    "severity",
    "target",
    "value",
    "message",
)


def _text(value: object) -> str:
    if value is None:
        return ""
    return value.isoformat() if isinstance(value, date) else str(value)


def assumptions_csv(entries: list[Assumption]) -> str:
    """Every judgement in force, with its default, who chose it, when and why."""
    rows = [{c: _text(getattr(e, c)) for c in ASSUMPTION_COLUMNS} for e in entries]
    frame = pl.DataFrame(rows, schema={c: pl.String for c in ASSUMPTION_COLUMNS})
    return frame.write_csv()


def diagnostics_csv(result: ReservingResult, extra: list[dict[str, Any]] | None = None) -> str:
    """The diagnostics of the methods; `extra` are rows of methods outside the triangles
    (MT17, MT18), already in the columns of the file."""
    rows: list[dict[str, Any]] = []
    for group in result.groups:
        for found in group.diagnostics:
            item = found.item
            rows.append(
                {
                    "segment": group.group[0],
                    "line": group.group[1],
                    "measure": found.measure,
                    "method": item.method,
                    "code": item.code,
                    "severity": item.severity,
                    "target": item.target,
                    "value": item.value,
                    "message": item.message,
                }
            )
    rows += extra or []
    for row in rows:
        if row["method"] in ROUNDED_METHODS:
            row["value"] = round_significant(row["value"])
    schema: dict[str, Any] = {c: pl.String for c in DIAGNOSTIC_COLUMNS}
    schema["value"] = pl.Float64
    return pl.DataFrame(rows, schema=schema).write_csv()


def anomalies_csv(anomalies: AnomalyResult) -> str:
    return anomalies.flags.select(ANOMALY_COLUMNS).write_csv()


def ultimates_csv(result: ReservingResult) -> str:
    return ultimates_table(result).write_csv()


def range_csv(result: ReservingResult) -> str:
    return range_table(result).write_csv()


def cash_flows_csv(result: ReservingResult) -> str:
    """MT07 expected payments by future period, on both price bases."""
    rows: list[dict[str, Any]] = []
    months = result.triangles.settings.development_period.months
    for group in result.groups:
        outcome = group.inflation_adjusted
        if not isinstance(outcome, InflationAdjusted):
            continue
        for flow in future_cash_flows(outcome, result.triangles.cut_off, months):
            rows.append(
                {
                    "segment": group.group[0],
                    "line": group.group[1],
                    "period": flow.period,
                    "start": flow.start,
                    "end": flow.end,
                    "payment_date": flow.payment_date,
                    "at_value_date_prices": flow.at_value_date_prices,
                    "nominal": flow.nominal,
                }
            )
    schema: dict[str, Any] = {
        "segment": pl.String,
        "line": pl.String,
        "period": pl.Int64,
        "start": pl.Date,
        "end": pl.Date,
        "payment_date": pl.Date,
        "at_value_date_prices": pl.Float64,
        "nominal": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema).write_csv()
