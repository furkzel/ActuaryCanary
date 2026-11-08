"""The tier B parts of a reserving page (record 0340): the ultimates of MT12, MT13, MT15 and
MT16 beside the tier A methods and the selection, the fitted tails (MT14), Munich paid and
incurred (MT12), the bootstrap (MT11) and the back test (MT22, AE02), each with the
diagnostics its method raised.

Read from the tables the run writes (`tier_b_ultimates.csv`, `tier_b_parameters.csv`,
`bootstrap_summary.csv`, `back_test.csv`, `sensitivity.csv`), so every number is a cell of a
named file; rounded per CV06 for the page only.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.modules import reserving_tier_b_output as tier_b_output
from actuarycanary.modules.reserving import GroupReserving
from actuarycanary.report import numbers
from actuarycanary.report.frames import of_line, table, text, value
from actuarycanary.report.language import t

TIER_B_COLUMNS = (
    ("munich_chain_ladder", "paid", "Munich chain ladder, paid", "MT12"),
    ("munich_chain_ladder", "incurred", "Munich chain ladder, incurred", "MT12"),
    ("benktander", "incurred", "Benktander, incurred", "MT13"),
    ("separation", "paid", "Separation, paid", "MT15"),
    ("frequency_severity", "incurred", "Frequency–severity, incurred", "MT16"),
)
TIER_B_METHODS = {
    "MT11": "Bootstrap (MT11)",
    "MT12": "Munich chain ladder (MT12)",
    "MT13": "Benktander (MT13)",
    "MT14": "Tail fit (MT14)",
    "MT15": "Separation (MT15)",
    "MT16": "Frequency–severity (MT16)",
    "MT22": "Back test (MT22)",
}
BACK_TEST_HORIZONS = 3  # horizons shown per method; back_test.csv has every one
CURVES = {"exponential_decay": "exponential decay", "inverse_power": "inverse power"}


def diagnostics_by_method(group: GroupReserving) -> dict[str, list[str]]:
    """The diagnostics of the line by method ID, as "CODE (measure): message"."""
    found: dict[str, list[str]] = defaultdict(list)
    for d in group.diagnostics:
        where = f" ({t(d.measure)})" if d.measure else ""
        found[d.item.method].append(f"{d.item.code}{where}: {d.item.message}")
    return dict(found)


def ultimate_columns(
    tables: Mapping[str, pl.DataFrame], group: GroupReserving
) -> tuple[list[tuple[str, list[float | None]]], list[str]]:
    """The tier B ultimates per origin of the line as (header, values by origin), and why a
    method has no column."""
    segment, line = group.group[0], group.group[1]
    rows = of_line(table(tables, tier_b_output.ULTIMATES_NAME), segment, line)
    origins = group.triangles["paid"].origins
    columns: list[tuple[str, list[float | None]]] = []
    notes: list[str] = []
    for method, measure, label, spec_id in TIER_B_COLUMNS:
        found = [r for r in rows if r["method"] == method and r["measure"] == measure]
        by_origin = {r["origin_period"]: value(r["ultimate"]) for r in found if r["origin_period"]}
        if not by_origin:
            reasons = {text(r["note"]) for r in found if r["note"]}
            if reasons:
                notes.append(
                    t(
                        "{title} did not run: {reason}.",
                        title=f"{t(label)} ({spec_id})",
                        reason="; ".join(sorted(reasons)),
                    )
                )
            continue
        basis = next((text(r["basis"]) for r in found if r["basis"]), "")
        header = f"{t(label)} ({spec_id})"
        if basis == "INFLATION_ADJUSTED":
            header = f"{header}, {t('value-date prices')}"
        columns.append((header, [by_origin.get(o) for o in origins]))
    return columns, notes


def _parameters(tables: Mapping[str, pl.DataFrame], group: GroupReserving) -> list[dict[str, Any]]:
    return of_line(table(tables, tier_b_output.PARAMETERS_NAME), group.group[0], group.group[1])


def tails(
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    diagnostics: Mapping[str, list[str]],
    effect: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """MT14 per triangle and curve: parameters, fit, tail factor and remainder, the curve MT14
    chose, and the tail the run used."""
    rows = [r for r in _parameters(tables, group) if r["method"] == "MT14"]
    fits = group.tier_b.tails if group.tier_b is not None else {}
    if not rows and not fits:
        return None
    out: list[dict[str, Any]] = []
    for measure in ("paid", "incurred"):
        mine = [r for r in rows if r["measure"] == measure]
        skipped = fits.get(measure)
        if isinstance(skipped, Skipped):
            out.append(
                {"measure": t(measure), "curve": numbers.EMPTY, "chosen": False,
                 "r_squared": numbers.EMPTY, "tail": numbers.EMPTY, "remainder": numbers.EMPTY,
                 "note": skipped.reason, "used": numbers.EMPTY}
            )  # fmt: skip
            continue
        chosen = next((text(r["note"]) for r in mine if r["item"] == "chosen_curve"), "")
        chain = group.chain_ladder.get(measure)
        used = chain.tail_factor if isinstance(chain, ChainLadder) else None
        for curve, label in CURVES.items():
            items = {r["item"]: r for r in mine if r["key"] == curve}
            not_used = next(
                (
                    text(r["note"])
                    for r in mine
                    if r["item"] == "curve_not_used" and r["key"] == curve
                ),
                "",
            )
            if not items and not not_used:
                continue
            out.append(
                {
                    "measure": t(measure),
                    "curve": t(label),
                    "chosen": curve == chosen,
                    "r_squared": numbers.factor(value(items.get("r_squared", {}).get("value"))),
                    "tail": numbers.factor(value(items.get("tail_factor", {}).get("value"))),
                    "remainder": numbers.ratio(value(items.get("tail_remainder", {}).get("value"))),
                    "note": not_used,
                    "used": numbers.factor(used),
                }
            )
    return {
        "rows": out,
        "diagnostics": diagnostics.get("MT14", []),
        "effect": effect,
    }


def munich(
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    diagnostics: Mapping[str, list[str]],
) -> dict[str, Any] | None:
    """Munich paid and incurred beside the separate chain ladders, with the paid over incurred
    ratio of each and the correlation parameters lambda."""
    segment, line = group.group[0], group.group[1]
    rows = of_line(table(tables, tier_b_output.ULTIMATES_NAME), segment, line)
    found = {
        (r["measure"], r["origin_period"]): value(r["ultimate"])
        for r in rows
        if r["method"] == "munich_chain_ladder" and r["origin_period"]
    }
    if not found:
        return None
    origins = group.triangles["paid"].origins
    chains = {m: group.chain_ladder.get(m) for m in ("paid", "incurred")}
    out = []
    for i, origin in enumerate(origins):
        cl = {
            m: float(c.ultimate[i]) if isinstance(c, ChainLadder) else None
            for m, c in chains.items()
        }
        mp, mi = found.get(("paid", origin)), found.get(("incurred", origin))
        out.append(
            {
                "origin": origin,
                "cells": [
                    numbers.amount(cl["paid"]),
                    numbers.amount(mp),
                    numbers.amount(cl["incurred"]),
                    numbers.amount(mi),
                    numbers.ratio(
                        cl["paid"] / cl["incurred"] if cl["paid"] and cl["incurred"] else None
                    ),
                    numbers.ratio(mp / mi if mp is not None and mi else None),
                ],
            }
        )
    lambdas = [
        t(
            "lambda {measure} {value} ({note})",
            measure=t(r["measure"]),
            value=numbers.factor(value(r["value"])),
            note=text(r["note"]),
        )
        for r in _parameters(tables, group)
        if r["method"] == "MT12" and r["item"] == "lambda"
    ]
    return {"rows": out, "lambdas": lambdas, "diagnostics": diagnostics.get("MT12", [])}


def bootstrap(
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    diagnostics: Mapping[str, list[str]],
) -> dict[str, Any]:
    """The MT11 total of the line against the chain-ladder reserve, or why it did not run."""
    rows = of_line(table(tables, tier_b_output.BOOTSTRAP_SUMMARY_NAME), *group.group[:2])
    total = next((r for r in rows if r["origin_period"] == "Total"), None)
    reasons = sorted({text(r["note"]) for r in rows if r["note"] and not r["origin_period"]})
    if total is None:
        return {
            "cells": [],
            "reason": "; ".join(reasons),
            "diagnostics": diagnostics.get("MT11", []),
        }
    return {
        "cells": [
            numbers.amount(value(total["reserve_chain_ladder"])),
            numbers.amount(value(total["mean"])),
            numbers.ratio(value(total["coefficient_of_variation"])),
            numbers.amount(value(total["p75"])),
            numbers.amount(value(total["p95"])),
            numbers.amount(value(total["p99_5"])),
            numbers.amount(value(total["tvar"])),
        ],
        "reason": "",
        "diagnostics": diagnostics.get("MT11", []),
    }


def back_test(
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    diagnostics: Mapping[str, list[str]],
) -> dict[str, Any] | None:
    """MT22 with AE02: bias and errors of each method on the first horizons, the share of
    actual outcomes inside the ranges, and the reasons for what could not be tested."""
    rows = of_line(table(tables, tier_b_output.BACK_TEST_NAME), *group.group[:2])
    if not rows:
        return None
    summary = [r for r in rows if r["kind"] == "summary"]
    horizons = sorted(
        {int(r["horizon_months"]) for r in summary if r["horizon_months"] is not None}
    )
    shown = set(horizons[:BACK_TEST_HORIZONS])
    out = [
        {
            "method": r["method"],
            "horizon": numbers.count(value(r["horizon_months"])),
            "origins": numbers.count(value(r["origins"])),
            "bias": numbers.ratio(value(r["bias"])),
            "mae": numbers.ratio(value(r["mean_absolute_error"])),
            "rmse": numbers.ratio(value(r["root_mean_square_error"])),
        }
        for r in summary
        if r["horizon_months"] is not None and int(r["horizon_months"]) in shown
    ]
    calibration = [
        {
            "method": r["method"],
            "horizon": numbers.count(value(r["horizon_months"])),
            "origins": numbers.count(value(r["origins"])),
            "inside": numbers.count(value(r["inside"])),
            "share": numbers.ratio(value(r["share"])),
        }
        for r in rows
        if r["kind"] == "range_calibration"
    ]
    notes = sorted({text(r["note"]) for r in rows if r["note"] and r["kind"] not in ("error",)})
    return {
        "rows": out,
        "calibration": calibration,
        "notes": notes,
        "horizons": len(horizons),
        "diagnostics": diagnostics.get("MT22", []),
    }


def tail_effect(tables: Mapping[str, pl.DataFrame], group: GroupReserving) -> dict[str, Any] | None:
    """The change of the selected IBNR when the tail of the curve MT14 chose replaces the
    run's tail (the `tail_fitted` row of sensitivity.csv)."""
    rows = of_line(table(tables, "sensitivity.csv"), *group.group[:2])
    found = next((r for r in rows if r["variant"] == "tail_fitted"), None)
    if found is None or value(found["value"]) is None:
        return None
    return {
        "base": numbers.amount(value(found["base"])),
        "value": numbers.amount(value(found["value"])),
        "change": numbers.change_ratio(value(found["relative"])),
    }


def line_tier_b(
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    spec: Callable[..., str],
) -> dict[str, Any]:
    """Everything tier B shows on the reserving page of one line."""
    diagnostics = diagnostics_by_method(group)
    _, notes = ultimate_columns(tables, group)
    tier_b_diagnostics = [
        {"method": TIER_B_METHODS[m], "messages": diagnostics[m]}
        for m in ("MT13", "MT15", "MT16")
        if m in diagnostics
    ]
    tier_a = [
        {"method": m, "messages": items}
        for m, items in sorted(diagnostics.items())
        if m not in TIER_B_METHODS
    ]
    return {
        "not_run": notes,
        "tails": tails(tables, group, diagnostics, tail_effect(tables, group)),
        "munich": munich(tables, group, diagnostics),
        "bootstrap": bootstrap(tables, group, diagnostics),
        "back_test": back_test(tables, group, diagnostics),
        "method_diagnostics": tier_b_diagnostics,
        "tier_a_diagnostics": tier_a,
        "footnotes": {
            "ultimates": t(
                "Tier A: {tier_a}. Tier B beside them: {tier_b}; rows of ultimates.csv and "
                "tier_b_ultimates.csv. The frequency–severity ultimate is at value-date prices "
                "when the price index is loaded.",
                tier_a=spec("MT02", "MT03", "MT04", "MT05", "MT07"),
                tier_b=spec("MT12", "MT13", "MT15", "MT16"),
            ),
            "tails": t(
                "Tail curves fitted to the selected factors ({spec}); rows of "
                "tier_b_parameters.csv. The run uses the MT02 tail unless the assumptions "
                "register selects a curve; the effect of the chosen curve is a row of "
                "sensitivity.csv.",
                spec=spec("MT14"),
            ),
            "munich": t(
                "Munich chain ladder ({spec}) beside the separate chain ladders ({mt02}); the "
                "Munich method brings paid over incurred closer to its observed level. Rows of "
                "tier_b_ultimates.csv and tier_b_parameters.csv.",
                spec=spec("MT12"),
                mt02=spec("MT02"),
            ),
            "bootstrap": t(
                "Over-dispersed Poisson bootstrap on the paid triangle ({spec}); row Total of "
                "bootstrap_summary.csv, simulations in bootstrap_distribution_<line>.parquet.",
                spec=spec("MT11"),
            ),
            "back_test": t(
                "Back test ({specs}): each method rerun on the data known at an earlier "
                "valuation and compared with the incurred known later; error = estimate over "
                "reference − 1. The first {n} horizons are shown; back_test.csv has every "
                "horizon and origin.",
                specs=spec("MT22", "AE02"),
                n=BACK_TEST_HORIZONS,
            ),
        },
    }


def merged_ultimates(
    ultimates: dict[str, Any], columns: list[tuple[str, list[float | None]]]
) -> dict[str, Any]:
    """The tier A table of `group_methods` with the tier B columns inserted before the
    selection; the total row sums a column only when every origin has a value."""
    if not columns:
        return {**ultimates, "tiers": ["A"] * len(ultimates["headers"])}
    rows = []
    for k, row in enumerate(ultimates["rows"]):
        if row["total"]:
            extra = []
            for _, values in columns:
                known = [v for v in values if v is not None]
                extra.append(
                    numbers.amount(float(np.sum(known)))
                    if len(known) == len(values)
                    else numbers.EMPTY
                )
        else:
            extra = [numbers.amount(values[k]) for _, values in columns]
        rows.append({**row, "cells": [*row["cells"], *extra]})
    return {
        "headers": [*ultimates["headers"], *(h for h, _ in columns)],
        "tiers": ["A"] * len(ultimates["headers"]) + ["B"] * len(columns),
        "rows": rows,
    }


__all__ = ["line_tier_b", "merged_ultimates", "ultimate_columns"]
