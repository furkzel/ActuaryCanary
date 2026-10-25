"""The data files of the tier B reserving methods, unrounded (CV06; record 0620).

`tier_b_ultimates.csv`  ultimates of MT12, MT13, MT15 and MT16 per origin, or the reason a
                         method did not run
`tier_b_parameters.csv` fitted quantities of MT11 to MT16 in one long table
`bootstrap_summary.csv`, `bootstrap_cash_flows.csv`, `bootstrap_residuals.csv`
                         the MT11 outputs of every group; its simulated reserves are kept
                         apart per group as `bootstrap_distribution_<segment>_<line>.parquet`
`back_test.csv`          MT22 with AE02: errors and their summaries per method and horizon,
                         the range calibration and the reasons

Diagnostics and the parameters in force go to `diagnostics.csv` and `assumptions.csv` with those
of tier A.
"""

import io
import re
from collections.abc import Callable
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.methods.back_testing import BackTest
from actuarycanary.methods.benktander import Benktander
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.frequency_severity import FrequencySeverity, Trend
from actuarycanary.methods.munich import Munich
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, Summary
from actuarycanary.methods.separation import NO_TAIL_LABEL, Separation
from actuarycanary.methods.tail import CurveFit, TailFit
from actuarycanary.modules.reserving import GroupReserving, ReservingResult
from actuarycanary.modules.reserving_tier_b import tail_outcome

ULTIMATES_NAME = "tier_b_ultimates.csv"
PARAMETERS_NAME = "tier_b_parameters.csv"
BOOTSTRAP_SUMMARY_NAME = "bootstrap_summary.csv"
BOOTSTRAP_CASH_FLOWS_NAME = "bootstrap_cash_flows.csv"
BOOTSTRAP_RESIDUALS_NAME = "bootstrap_residuals.csv"
BACK_TEST_NAME = "back_test.csv"
DISTRIBUTION_PREFIX = "bootstrap_distribution_"
DISTRIBUTION_SUFFIX = ".parquet"

ULTIMATE_COLUMNS = (
    "segment", "line", "origin_period", "method", "measure", "basis", "ultimate", "note",
)  # fmt: skip
PARAMETER_COLUMNS = ("segment", "line", "method", "measure", "item", "key", "value", "note")
PERCENTILE_NAMES = {0.5: "p50", 0.75: "p75", 0.9: "p90", 0.95: "p95", 0.99: "p99", 0.995: "p99_5"}
BACK_TEST_COLUMNS = (
    "segment", "line", "kind", "method", "horizon_months", "origin_period", "estimate",
    "reference", "error", "label", "origins", "bias", "mean_absolute_error",
    "root_mean_square_error", "inside", "share", "note",
)  # fmt: skip


def _key(group: GroupReserving) -> dict[str, str]:
    return {"segment": group.group[0], "line": group.group[1]}


def _frame(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema, infer_schema_length=None)


# --- ultimates ------------------------------------------------------------------------------


def ultimates_table(result: ReservingResult) -> pl.DataFrame:
    """MT12, MT13, MT15 and MT16 per origin; a method that did not run has one row with its
    reason. The separation method carries no tail; the frequency–severity ultimate is at the
    prices named in `basis`."""
    rows: list[dict[str, Any]] = []
    for group in result.groups:
        tier_b = group.tier_b
        if tier_b is None:
            continue
        base = _key(group)

        def add(
            origins: tuple[str, ...],
            method: str,
            measure: str,
            values: np.ndarray,
            basis: str = "",
            note: str = "",
            notes: dict[int, str] | None = None,
            _base: dict[str, str] = base,
        ) -> None:
            for i, origin in enumerate(origins):
                value = float(values[i])
                rows.append(
                    {
                        **_base,
                        "origin_period": origin,
                        "method": method,
                        "measure": measure,
                        "basis": basis,
                        "ultimate": value if np.isfinite(value) else None,
                        "note": (notes or {}).get(i, note),
                    }
                )

        def refused(
            method: str, measure: str, found: Skipped, _base: dict[str, str] = base
        ) -> None:
            rows.append(
                {**_base, "origin_period": "", "method": method, "measure": measure,
                 "basis": "", "ultimate": None, "note": found.reason}
            )  # fmt: skip

        incurred = group.triangles["incurred"]
        if isinstance(tier_b.munich, Skipped):
            refused("munich_chain_ladder", "paid and incurred", tier_b.munich)
        else:
            add(incurred.origins, "munich_chain_ladder", "paid", tier_b.munich.paid_ultimate)
            add(incurred.origins, "munich_chain_ladder", "incurred",
                tier_b.munich.incurred_ultimate)  # fmt: skip
        measure = tier_b.benktander_measure
        if isinstance(tier_b.benktander, Skipped):
            refused("benktander", measure, tier_b.benktander)
        else:
            add(group.triangles[measure].origins, "benktander", measure, tier_b.benktander.ultimate,
                notes=tier_b.benktander.not_run)  # fmt: skip
        if isinstance(tier_b.separation, Skipped):
            refused("separation", "paid", tier_b.separation)
        else:
            add(tier_b.separation_origins, "separation", "paid", tier_b.separation.ultimate,
                note=NO_TAIL_LABEL)  # fmt: skip
        if isinstance(tier_b.frequency_severity, Skipped):
            refused("frequency_severity", "incurred", tier_b.frequency_severity)
        else:
            add(
                tier_b.frequency_origins,
                "frequency_severity",
                "incurred",
                tier_b.frequency_severity.ultimate,
                basis=tier_b.frequency_value_basis,
                note=(
                    "at value-date prices"
                    if tier_b.frequency_value_basis == "INFLATION_ADJUSTED"
                    else "at nominal prices"
                ),
            )
    schema: dict[str, Any] = {c: pl.String for c in ULTIMATE_COLUMNS}
    schema["ultimate"] = pl.Float64
    return _frame(rows, schema)


# --- long table of fitted quantities --------------------------------------------------------


def _trend(add: Callable[..., None], method: str, name: str, trend: Trend | None) -> None:
    if trend is None:
        return
    add(method, "incurred", name, "intercept", trend.intercept)
    add(method, "incurred", name, "slope", trend.slope)
    add(method, "incurred", name, "annual_rate", trend.rate)
    add(method, "incurred", name, "origins_used", float(len(trend.origins)))


def parameters_table(result: ReservingResult) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for group in result.groups:
        tier_b = group.tier_b
        if tier_b is None:
            continue
        base = _key(group)

        def add(
            method: str,
            measure: str,
            item: str,
            key: str,
            value: float | None,
            note: str = "",
            _base: dict[str, str] = base,
        ) -> None:
            rows.append(
                {**_base, "method": method, "measure": measure, "item": item, "key": key,
                 "value": value, "note": note}
            )  # fmt: skip

        boot = tier_b.bootstrap
        if isinstance(boot, OdpBootstrap):
            add("MT11", "paid", "scale_parameter", "", boot.scale_parameter)
            add("MT11", "paid", "degrees_of_freedom", "", float(boot.degrees_of_freedom))
            add("MT11", "paid", "simulations", "", float(boot.n_simulations))
            add("MT11", "paid", "seed", "", float(boot.seed))
            add("MT11", "paid", "tail_factor", "", boot.tail_factor)
            add("MT11", "paid", "bias", "", boot.bias, "mean simulated reserve over the "
                "chain-ladder reserve, minus 1")  # fmt: skip
        munich = tier_b.munich
        if isinstance(munich, Munich):
            n_paid, n_incurred = munich.n_pairs
            add("MT12", "paid", "lambda", "", munich.lambda_paid, f"{n_paid} residual pairs")
            add("MT12", "incurred", "lambda", "", munich.lambda_incurred,
                f"{n_incurred} residual pairs")  # fmt: skip
        blend = tier_b.benktander
        if isinstance(blend, Benktander):
            add("MT13", tier_b.benktander_measure, "iterations", "", float(blend.iterations))
            origins = group.triangles[tier_b.benktander_measure].origins
            for i, origin in enumerate(origins):
                add("MT13", tier_b.benktander_measure, "weight_on_chain_ladder", origin,
                    float(blend.weight[i]))  # fmt: skip
        for measure, fit in sorted(tier_b.tails.items()):
            outcome = tail_outcome(fit)
            if isinstance(outcome, Skipped):
                add("MT14", measure, "not_fitted", "", None, outcome.reason)
                continue
            if not isinstance(outcome, TailFit):
                continue
            add("MT14", measure, "chosen_curve", "", None, outcome.curve.value)
            for curve, found in outcome.fits.items():
                if isinstance(found, CurveFit):
                    for name, value in (
                        ("a", found.a),
                        ("b", found.b),
                        ("r_squared", found.r_squared),
                        ("tail_factor", found.tail_factor),
                        ("tail_remainder", found.tail_remainder),
                    ):
                        add("MT14", measure, name, curve.value, float(value))
                else:
                    add("MT14", measure, "curve_not_used", curve.value, None, found.reason)
        separation = tier_b.separation
        if isinstance(separation, Separation):
            n = separation.n_past
            ages = group.triangles["paid"].ages
            for j in range(n):
                add("MT15", "paid", "pattern", str(ages[j]), float(separation.pattern[j]))
            for k, value in enumerate(separation.index):
                add("MT15", "paid", "calendar_index", str(k), float(value),
                    "future" if k >= n else "")  # fmt: skip
            add("MT15", "paid", "future_growth", "", separation.growth,
                f"per period; {separation.future_index.value}")  # fmt: skip
        fs = tier_b.frequency_severity
        if isinstance(fs, FrequencySeverity):
            for i, origin in enumerate(tier_b.frequency_origins):
                add("MT16", "incurred", "ultimate_count", origin, float(fs.ultimate_counts[i]))
                add("MT16", "incurred", "observed_severity", origin, float(fs.severity[i]),
                    "mature" if fs.mature[i] else "")  # fmt: skip
                add("MT16", "incurred", "projected_severity", origin,
                    float(fs.projected_severity[i]))  # fmt: skip
                add("MT16", "incurred", "catastrophe_ultimate", origin,
                    float(fs.catastrophe_ultimate[i]))  # fmt: skip
                if fs.frequency is not None:
                    add("MT16", "incurred", "frequency", origin, float(fs.frequency[i]))
            _trend(add, "MT16", "severity_trend", fs.severity_trend)
            _trend(add, "MT16", "frequency_trend", fs.frequency_trend)
    schema: dict[str, Any] = {c: pl.String for c in PARAMETER_COLUMNS}
    schema["value"] = pl.Float64
    return _frame(rows, schema)


# --- the bootstrap ----------------------------------------------------------------------------


def _summary_row(summary: Summary) -> dict[str, Any]:
    return {
        "mean": summary.mean,
        "standard_deviation": summary.standard_deviation,
        "coefficient_of_variation": summary.coefficient_of_variation,
        **{PERCENTILE_NAMES[p]: v for p, v in summary.percentiles.items() if p in PERCENTILE_NAMES},
        "var": summary.value_at_risk,
        "tvar": summary.tail_value_at_risk,
    }


def _summary_schema(leading: dict[str, Any]) -> dict[str, Any]:
    names = ("mean", "standard_deviation", "coefficient_of_variation", *PERCENTILE_NAMES.values(),
             "var", "tvar")  # fmt: skip
    return {**leading, **{n: pl.Float64 for n in names}}


def bootstrap_summary(result: ReservingResult) -> pl.DataFrame:
    """MT11 `summary` per group, origin and in total, with the chain-ladder reserve beside it;
    a group where it did not run has one row with the reason."""
    rows: list[dict[str, Any]] = []
    for group in result.groups:
        if group.tier_b is None:
            continue
        boot = group.tier_b.bootstrap
        base = _key(group)
        if isinstance(boot, Skipped):
            rows.append({**base, "origin_period": "", "note": boot.reason})
            continue
        origins = group.triangles["paid"].origins
        per_origin, total = boot.summary()
        reserve = boot.chain_ladder_reserve
        for i, summary in enumerate(per_origin):
            rows.append(
                {**base, "origin_period": origins[i], "reserve_chain_ladder": float(reserve[i]),
                 **_summary_row(summary), "note": ""}
            )  # fmt: skip
        rows.append(
            {**base, "origin_period": "Total", "reserve_chain_ladder": float(reserve.sum()),
             **_summary_row(total), "note": ""}
        )  # fmt: skip
    schema = _summary_schema(
        {
            "segment": pl.String,
            "line": pl.String,
            "origin_period": pl.String,
            "reserve_chain_ladder": pl.Float64,
        }  # fmt: skip
    )
    return _frame(rows, {**schema, "note": pl.String})


def bootstrap_cash_flows(result: ReservingResult) -> pl.DataFrame:
    """MT11 `simulated_cash_flows`: future payments by calendar period after the cut-off."""
    rows: list[dict[str, Any]] = []
    for group in result.groups:
        if group.tier_b is None or not isinstance(group.tier_b.bootstrap, OdpBootstrap):
            continue
        for period, summary in enumerate(group.tier_b.bootstrap.cash_flow_summary(), start=1):
            rows.append({**_key(group), "period": period, **_summary_row(summary)})
    schema = _summary_schema({"segment": pl.String, "line": pl.String, "period": pl.Int64})
    return _frame(rows, schema)


def bootstrap_residuals(result: ReservingResult) -> pl.DataFrame:
    """MT11 `residuals`: unscaled and adjusted Pearson residuals per cell."""
    parts: list[pl.DataFrame] = []
    for group in result.groups:
        if group.tier_b is None or not isinstance(group.tier_b.bootstrap, OdpBootstrap):
            continue
        triangle = group.triangles["paid"]
        table = group.tier_b.bootstrap.residual_table(triangle.origins, triangle.ages)
        key = _key(group)
        parts.append(table.with_columns(*[pl.lit(v).alias(k) for k, v in key.items()]))
    columns = ["segment", "line", "origin", "age", "diagonal", "unscaled", "adjusted", "in_pool",
               "fitted"]  # fmt: skip
    if not parts:
        return pl.DataFrame(schema={c: pl.String for c in columns})
    return pl.concat(parts).select(columns)


def distribution_files(result: ReservingResult) -> dict[str, bytes]:
    """MT11 `reserve_distribution`: the simulated reserves of each group as parquet, one row
    per simulation with a column per origin and `total`."""
    files: dict[str, bytes] = {}
    for group in result.groups:
        if group.tier_b is None or not isinstance(group.tier_b.bootstrap, OdpBootstrap):
            continue
        label = re.sub(r"[^A-Za-z0-9_.-]+", "-", "_".join(group.group)).strip("-")
        buffer = io.BytesIO()
        frame = group.tier_b.bootstrap.distribution_frame(group.triangles["paid"].origins)
        frame.write_parquet(buffer, compression="zstd", statistics=False)
        files[f"{DISTRIBUTION_PREFIX}{label}{DISTRIBUTION_SUFFIX}"] = buffer.getvalue()
    return files


# --- back-test (MT22) and AE02 ----------------------------------------------------------------


def back_test_rows(group: GroupReserving, test: BackTest | Skipped) -> list[dict[str, Any]]:
    base = _key(group)
    if isinstance(test, Skipped):
        return [{**base, "kind": "not_run", "note": test.reason}]
    rows: list[dict[str, Any]] = []
    for e in test.errors:
        rows.append(
            {**base, "kind": "error", "method": e.method, "horizon_months": e.horizon_months,
             "origin_period": e.origin, "estimate": e.estimate, "reference": e.reference,
             "error": e.error, "label": e.label}
        )  # fmt: skip
    for s in test.summaries:
        rows.append(
            {**base, "kind": "summary", "method": s.method, "horizon_months": s.horizon_months,
             "origins": s.origins, "bias": s.bias, "mean_absolute_error": s.mean_absolute_error,
             "root_mean_square_error": s.root_mean_square_error}
        )  # fmt: skip
    for n in test.not_summarised:
        rows.append(
            {**base, "kind": "not_summarised", "method": n.method,
             "horizon_months": n.horizon_months, "note": n.reason}
        )  # fmt: skip
    for r in test.ranges:
        rows.append(
            {**base, "kind": "range_calibration", "method": r.method,
             "horizon_months": r.horizon_months, "origins": r.origins, "inside": r.inside,
             "share": r.share}
        )  # fmt: skip
    for (method, horizon), reason in sorted(test.not_run.items()):
        rows.append(
            {**base, "kind": "not_run", "method": method, "horizon_months": horizon,
             "note": reason}
        )  # fmt: skip
    for horizon, reason in sorted(test.horizons_not_computed.items()):
        rows.append(
            {**base, "kind": "horizon_not_computed", "horizon_months": horizon, "note": reason}
        )  # fmt: skip
    return rows


def back_test_table(result: ReservingResult) -> pl.DataFrame:
    """MT22 and AE02 of every group: errors per method, origin and horizon, summaries per
    method and horizon, the range calibration and what did not run."""
    rows: list[dict[str, Any]] = []
    for group in result.groups:
        if group.tier_b is not None:
            rows += back_test_rows(group, group.tier_b.back_test)
    schema: dict[str, Any] = {c: pl.Float64 for c in BACK_TEST_COLUMNS}
    for text in ("segment", "line", "kind", "method", "origin_period", "label", "note"):
        schema[text] = pl.String
    schema["horizon_months"] = pl.Int64
    schema["origins"] = pl.Int64
    schema["inside"] = pl.Int64
    return _frame(rows, schema).select(*BACK_TEST_COLUMNS)


def ae02_table(result: ReservingResult) -> pl.DataFrame:
    """AE02 as the measure engine hands it on: the errors and their summaries."""
    table = back_test_table(result)
    return table.filter(pl.col("kind").is_in(["error", "summary"]))


def tables(result: ReservingResult) -> dict[str, pl.DataFrame]:
    """Every csv file of the tier B methods by file name."""
    return {
        ULTIMATES_NAME: ultimates_table(result),
        PARAMETERS_NAME: parameters_table(result),
        BOOTSTRAP_SUMMARY_NAME: bootstrap_summary(result),
        BOOTSTRAP_CASH_FLOWS_NAME: bootstrap_cash_flows(result),
        BOOTSTRAP_RESIDUALS_NAME: bootstrap_residuals(result),
        BACK_TEST_NAME: back_test_table(result),
    }


def measures_run(result: ReservingResult) -> list[str]:
    """AE02 when a back-test produced errors for at least one group."""
    ran = any(
        g.tier_b is not None
        and isinstance(g.tier_b.back_test, BackTest)
        and g.tier_b.back_test.errors
        for g in result.groups
    )
    return ["AE02"] if ran else []
