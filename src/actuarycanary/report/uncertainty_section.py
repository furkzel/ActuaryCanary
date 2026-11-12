"""The uncertainty page (M12, record 0342): the selected reserve with its range, the Mack
lognormal range (RS03) and the bootstrap (RS05) side by side, the distribution of the
simulated reserve with VaR and TVaR, the effect of the fitted tail (MT14), the expected cash
flows nominal and discounted (RS04, CV10) with the curve, the assumptions behind the totals
and the calibration evidence.

Every block names the value basis it shows (NOMINAL or DISCOUNTED), so the page can switch
between the bases the run computed without a new run (record 0344). Numbers are cells of
`risk_measures.csv`, `risk_cash_flows.csv`, `risk_distribution.parquet`, `discount_curve.csv`,
`back_test.csv` and `sensitivity.csv`, rounded for the page only.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.modules import reserving_tier_b_output as tier_b_output
from actuarycanary.modules.uncertainty import (
    ALL_LINES,
    BOOTSTRAP_SOURCE,
    DISCOUNTED,
    EXPECTED_SOURCE,
    MACK_SOURCE,
    NOMINAL,
    TOTAL,
    LineRisk,
    UncertaintyResult,
)
from actuarycanary.report import coverage, numbers
from actuarycanary.report.charts import INK, MUTED, _layout, _round
from actuarycanary.report.frames import table, text, value
from actuarycanary.report.language import t

BASES = (NOMINAL, DISCOUNTED)
BINS = 40  # bars of the histogram of the simulated reserve
LOW = 0.05  # the headline range: 5th to 95th percentile
LEFT_OUT_FLOOR = 0.005  # a selected unpaid below half a cent is rounding noise, not an origin
BASIS_TOKENS = {NOMINAL: "--value-nominal", DISCOUNTED: "--value-discounted"}
SOURCE_LABELS = {
    MACK_SOURCE: "Mack, lognormal approximation (RS03)",
    BOOTSTRAP_SOURCE: "Bootstrap (RS05, MT11)",
    EXPECTED_SOURCE: "Expected cash flows (RS04)",
}


def basis_colour(basis: str) -> str:
    return f"var({BASIS_TOKENS[basis]})"


def _line_name(segment: str, line: str) -> str:
    return t(ALL_LINES) if segment == ALL_LINES else f"{segment} · {line}"


def _totals(risk: pl.DataFrame) -> list[dict[str, Any]]:
    if not risk.height:
        return []
    return risk.filter(pl.col("origin_period") == TOTAL).to_dicts()


def _column(segment: str, line: str, basis: str) -> str:
    name = ALL_LINES if segment == ALL_LINES else f"{segment} / {line}"
    return f"{name} (discounted)" if basis == DISCOUNTED else name


def _lognormal_low(mean: float | None, sd: float | None, p: float = LOW) -> float | None:
    """The p-quantile of the lognormal with this mean and standard deviation (RS03)."""
    if mean is None or sd is None or mean <= 0 or sd <= 0:
        return None
    from scipy.stats import norm

    s2 = math.log1p((sd / mean) ** 2)
    return float(math.exp(math.log(mean) - s2 / 2 + math.sqrt(s2) * norm.ppf(p)))


def _sims(distribution: pl.DataFrame, column: str) -> np.ndarray | None:
    if column not in distribution.columns:
        return None
    return distribution[column].drop_nulls().to_numpy().astype(float)


def _coverage_text(
    tables: Mapping[str, pl.DataFrame] | None, source: str, segment: str, line: str
) -> str:
    """The back-test coverage of the range of this source for this line, or pooled over all
    lines (R12); empty for the expected cash flows, which carry no range."""
    method = {MACK_SOURCE: coverage.MACK_METHOD, BOOTSTRAP_SOURCE: coverage.BOOTSTRAP_METHOD}.get(
        source
    )
    if method is None or tables is None:
        return ""
    where = (None, None) if segment == ALL_LINES else (segment, line)
    return coverage.sentence(coverage.observed(tables, method, *where))


def selected_totals(lines: tuple[LineRisk, ...]) -> dict[tuple[str, str], float]:
    """The selected unpaid per line and, added, of all lines: the one total of the run that
    every table and sentence calls "the selected unpaid" (A1a, R07, record 0752)."""
    totals = {line.key: line.selected_total for line in lines}
    if totals:
        totals[(ALL_LINES, ALL_LINES)] = sum(totals.values())
    return totals


def headline(
    risk: pl.DataFrame,
    distribution: pl.DataFrame,
    basis: str,
    selected: Mapping[tuple[str, str], float] | None = None,
    tables: Mapping[str, pl.DataFrame] | None = None,
) -> list[dict[str, Any]]:
    """Per line and for all lines: the selected unpaid and the mean of the range with its 5th to
    95th percentile and the coefficient of variation, from the bootstrap where it ran, else
    from Mack. On the discounted basis the row also holds the nominal mean of the same range
    and the discount effect on that mean, so that nominal mean less effect is the mean shown
    (R06): the discount effect of the expected cash flows (RS04) is in `present_values`."""
    out = []
    rows = _totals(risk)
    keys = list(dict.fromkeys((r["segment"], r["line"]) for r in rows))
    for segment, line in keys:
        mine = [r for r in rows if (r["segment"], r["line"]) == (segment, line)]
        boot = next(
            (r for r in mine if r["source"] == BOOTSTRAP_SOURCE and r["value_basis"] == basis), None
        )
        mack = next(
            (r for r in mine if r["source"] == MACK_SOURCE and r["value_basis"] == basis), None
        )
        expected = next(
            (r for r in mine if r["source"] == EXPECTED_SOURCE and r["value_basis"] == basis), None
        )
        chosen = boot or mack
        if chosen is None and expected is None:
            continue
        low = None
        if boot is not None:
            sims = _sims(distribution, _column(segment, line, basis))
            low = float(np.quantile(sims, LOW)) if sims is not None and sims.size else None
        elif mack is not None:
            low = _lognormal_low(value(mack["mean"]), value(mack["standard_deviation"]))
        shown = chosen or expected or {}
        reserve = value(shown.get("mean"))
        before, effect = value(shown.get("nominal_mean")), value(shown.get("discount_effect"))
        out.append(
            {
                "line": _line_name(segment, line),
                "selected": numbers.amount((selected or {}).get((segment, line))),
                "reserve": numbers.amount(reserve),
                "nominal": numbers.amount(before),
                "effect": numbers.amount(effect),
                "low": numbers.amount(low),
                "high": numbers.amount(value(chosen["p95"])) if chosen else numbers.EMPTY,
                "cv": numbers.ratio(value(chosen["coefficient_of_variation"]))
                if chosen
                else numbers.EMPTY,
                "source": t(SOURCE_LABELS[chosen["source"]])
                if chosen
                else t(SOURCE_LABELS[EXPECTED_SOURCE]),
                "coverage": _coverage_text(tables, chosen["source"], segment, line)
                if chosen
                else "",
            }
        )
    return out


def present_values(risk: pl.DataFrame) -> list[dict[str, Any]]:
    """The present value of the selected unpaid by the expected cash flows (RS04), per line and
    for all lines: selected unpaid less the discount effect is the present value. One
    definition in the table (R06); the simulated means are in the table above it."""
    out = []
    for r in _totals(risk):
        if r["source"] != EXPECTED_SOURCE or r["value_basis"] != DISCOUNTED:
            continue
        out.append(
            {
                "line": _line_name(r["segment"], r["line"]),
                "selected": numbers.amount(value(r["nominal_mean"])),
                "effect": numbers.amount(value(r["discount_effect"])),
                "present": numbers.amount(value(r["mean"])),
            }
        )
    return out


@dataclass(frozen=True)
class Bridge:
    """From the selected unpaid of a line to the mean of its simulation (R05, record 0752)."""

    selected: float
    left_out: float  # selected unpaid of the origins that carry no simulated development
    left_out_origins: tuple[tuple[str, float], ...]
    other: (
        float  # what is left: the simulation mean of the other origins less their selected unpaid
    )
    mean: float  # the simulated mean

    @property
    def balance(self) -> float:
        """selected - left out + other; equal to the simulated mean."""
        return self.selected - self.left_out + self.other


def bridge_of(origins: tuple[str, ...], selected: np.ndarray, origin_sims: np.ndarray) -> Bridge:
    """The bridge of one line from its selected unpaid per origin and its simulations per
    origin (simulations x origins, scaled as M12 scales them). An origin is left out when it has
    a selected unpaid of half a cent or more but a simulated mean of zero: it is fully developed
    in the simulated triangle, carries no simulated development and keeps zero in the simulation
    (0325, 0349)."""
    means = origin_sims.mean(axis=0)
    picked = np.nan_to_num(selected, nan=0.0)
    out = (np.abs(picked) >= LEFT_OUT_FLOOR) & (np.abs(means) < LEFT_OUT_FLOOR)
    left = tuple((origins[i], float(picked[i])) for i in np.nonzero(out)[0])
    total, left_out, mean = float(picked.sum()), float(picked[out].sum()), float(means.sum())
    return Bridge(total, left_out, left, mean - (total - left_out), mean)


def _discounted_means(risk: pl.DataFrame) -> dict[tuple[str, str], float]:
    return {
        (r["segment"], r["line"]): value(r["mean"]) or 0.0
        for r in _totals(risk)
        if r["source"] == BOOTSTRAP_SOURCE and r["value_basis"] == DISCOUNTED
    }


def bridge_table(result: UncertaintyResult, basis: str) -> dict[str, Any] | None:
    """Steps as rows, the lines and all lines as columns: selected unpaid, less the origins
    without simulated development, plus the remaining difference, equals the simulated mean;
    on the discounted basis the discount effect on the simulated mean in its own row."""
    columns: list[tuple[str, Bridge | None, float | None]] = []
    discounted = _discounted_means(result.risk) if basis == DISCOUNTED else {}
    for line in result.lines:
        if line.origin_sims is None:
            columns.append((_line_name(*line.key), None, None))
            continue
        found = bridge_of(line.origins, line.selected_unpaid, line.origin_sims)
        columns.append((_line_name(*line.key), found, discounted.get(line.key)))
    done = [c for c in columns if c[1] is not None]
    if not done:
        return None
    if len(done) == len(columns) and len(columns) > 1:
        total = Bridge(
            sum(c[1].selected for c in done),  # type: ignore[union-attr]
            sum(c[1].left_out for c in done),  # type: ignore[union-attr]
            (),
            sum(c[1].other for c in done),  # type: ignore[union-attr]
            sum(c[1].mean for c in done),  # type: ignore[union-attr]
        )
        columns.append(
            (
                t(ALL_LINES),
                total,
                (
                    sum(c[2] or 0.0 for c in done)
                    if basis == DISCOUNTED and all(c[2] is not None for c in done)
                    else None
                ),
            )
        )

    def cells(pick: Callable[[Bridge, float | None], float | None]) -> list[str]:
        return [
            numbers.amount(pick(b, d)) if b is not None else numbers.EMPTY for _, b, d in columns
        ]

    steps = [
        (t("Selected unpaid"), cells(lambda b, d: b.selected)),
        (t("less the origins without simulated development"), cells(lambda b, d: -b.left_out)),
        (
            t("plus the difference of the simulation for the other origins"),
            cells(lambda b, d: b.other),
        ),
        (t("Mean of the simulation, nominal"), cells(lambda b, d: b.mean)),
    ]
    if basis == DISCOUNTED:
        steps += [
            (
                t("less the discount effect on the simulated mean (RS05)"),
                cells(lambda b, d: None if d is None else d - b.mean),
            ),
            (t("Mean of the simulation, present value"), cells(lambda b, d: d)),
        ]
    left = [
        {
            "line": _line_name(*line.key),
            "origin": origin,
            "amount": numbers.amount(amount),
        }
        for line in result.lines
        if line.origin_sims is not None
        for origin, amount in bridge_of(
            line.origins, line.selected_unpaid, line.origin_sims
        ).left_out_origins
    ]
    return {"heads": [c[0] for c in columns], "steps": steps, "left_out": left}


def ranges(
    risk: pl.DataFrame, basis: str, tables: Mapping[str, pl.DataFrame] | None = None
) -> list[dict[str, Any]]:
    """RS03 and RS05 side by side per line and for all lines on one basis."""
    out = []
    for r in _totals(risk):
        if r["value_basis"] != basis or r["source"] == EXPECTED_SOURCE:
            continue
        out.append(
            {
                "line": _line_name(r["segment"], r["line"]),
                "source": t(SOURCE_LABELS.get(str(r["source"]), str(r["source"]))),
                "cells": [
                    numbers.amount(value(r["mean"])),
                    numbers.ratio(value(r["coefficient_of_variation"])),
                    numbers.amount(value(r["p50"])),
                    numbers.amount(value(r["p75"])),
                    numbers.amount(value(r["p95"])),
                    numbers.amount(value(r["value_at_risk"])),
                    numbers.amount(value(r["tail_value_at_risk"])),
                ],
                "simulations": numbers.count(value(r["simulations"])),
                "coverage": _coverage_text(tables, str(r["source"]), r["segment"], r["line"]),
                "label": text(r["label"]),
                "note": text(r["note"]),
            }
        )
    return out


def range_figure(
    risk: pl.DataFrame,
    basis: str,
    currency: str,
    tables: Mapping[str, pl.DataFrame] | None = None,
) -> dict[str, Any] | None:
    """The ranges drawn as ranges: a light bar from the median to the 99.5th percentile, a dark
    bar from the 75th to the 95th, the mean as a diamond, one row per line and source."""
    rows = [
        r
        for r in _totals(risk)
        if r["value_basis"] == basis
        and r["source"] != EXPECTED_SOURCE
        and value(r["p50"]) is not None
    ]
    if not rows:
        return None
    colour = basis_colour(basis)
    data: list[dict[str, Any]] = []
    labels = []
    for r in rows:
        source = t("bootstrap") if r["source"] == BOOTSTRAP_SOURCE else t("Mack")
        label = f"{_line_name(r['segment'], r['line'])} · {source}"
        if r["source"] == MACK_SOURCE and tables is not None:
            found = coverage.observed(
                tables,
                coverage.MACK_METHOD,
                *((None, None) if r["segment"] == ALL_LINES else (r["segment"], r["line"])),
            )
            label += (
                " ("
                + (
                    t("back-test coverage {share}", share=numbers.ratio(found.share))
                    if found
                    else t("no back-test")
                )
                + ")"
            )
        labels.append(label)
        for low, high, width, opacity, name in (
            ("p50", "p99_5", 8, 0.35, t("median to 99.5th percentile")),
            ("p75", "p95", 14, 0.9, t("75th to 95th percentile")),
        ):
            data.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "x": [_round(value(r[low])), _round(value(r[high]))],
                    "y": [label, label],
                    "line": {"color": colour, "width": width},
                    "opacity": opacity,
                    "hovertemplate": t(
                        "{label}: %{x:,.0f} {currency}<extra></extra>",
                        label=name,
                        currency=currency,
                    ),
                }
            )
        data.append(
            {
                "type": "scatter",
                "mode": "markers",
                "x": [_round(value(r["mean"]))],
                "y": [label],
                "marker": {"color": INK, "symbol": "diamond", "size": 10},
                "hovertemplate": t("Mean: %{x:,.0f} {currency}<extra></extra>", currency=currency),
            }
        )
    title = (
        t("Reserve ranges, present value, {currency}", currency=currency)
        if basis == DISCOUNTED
        else t("Reserve ranges, nominal, {currency}", currency=currency)
    )
    return {
        "data": data,
        "layout": _layout(
            title,
            t("Reserve ({currency})", currency=currency),
            "",
            yaxis={"type": "category", "autorange": "reversed", "automargin": True},
            height=max(180, 60 + 36 * len(labels)),
            margin={"l": 200, "r": 16, "t": 40, "b": 48},
        ),
    }


AXIS_LOW, AXIS_HIGH = 0.005, 0.995  # the histogram axis: 0.5th to 99.5th percentile (R21)


def histogram(
    risk: pl.DataFrame, distribution: pl.DataFrame, basis: str, currency: str
) -> list[tuple[str, dict[str, Any], str]]:
    """One histogram per simulated column on this basis (a line with a bootstrap, and all lines
    when every line has one), with the mean, VaR and TVaR as vertical lines. A few extreme
    draws would put nearly all the mass into two bars, so the axis runs from the 0.5th to the
    99.5th percentile of the simulations; the third item is the caption that states the
    extremes, the share outside the axis and the marks that fall outside (R21). The
    simulations in the file stay complete."""
    out = []
    for r in _totals(risk):
        if r["source"] != BOOTSTRAP_SOURCE or r["value_basis"] != basis:
            continue
        sims = _sims(distribution, _column(r["segment"], r["line"], basis))
        if sims is None or not sims.size:
            continue
        low, high = (float(x) for x in np.quantile(sims, [AXIS_LOW, AXIS_HIGH]))
        if high <= low:  # no spread: draw all of it
            low, high = float(sims.min()), float(sims.max())
        counts, edges = np.histogram(sims, bins=BINS, range=(low, high))
        centres = (edges[:-1] + edges[1:]) / 2
        outside = int(((sims < low) | (sims > high)).sum())
        marks = [
            (value(r["mean"]), t("mean"), "solid"),
            (
                value(r["value_at_risk"]),
                t("VaR {level}", level=numbers.ratio(value(r["var_level"]))),
                "dash",
            ),
            (
                value(r["tail_value_at_risk"]),
                t("TVaR {level}", level=numbers.ratio(value(r["tvar_level"]))),
                "dot",
            ),
        ]
        shown = [m for m in marks if m[0] is not None and low <= m[0] <= high]
        beyond = [m for m in marks if m[0] is not None and not low <= m[0] <= high]
        caption = t(
            "Axis from the 0.5th to the 99.5th percentile of the simulations ({low} to {high}); "
            "minimum {minimum}, maximum {maximum}; {share} of the {n} simulations are outside "
            "the axis.",
            low=numbers.amount(low),
            high=numbers.amount(high),
            minimum=numbers.amount(float(sims.min())),
            maximum=numbers.amount(float(sims.max())),
            share=numbers.ratio(outside / sims.size),
            n=numbers.count(sims.size),
        )
        if beyond:
            caption += " " + t(
                "Beyond the axis: {list}.",
                list=", ".join(f"{name} {numbers.amount(x)}" for x, name, _ in beyond),
            )
        layout = _layout(
            t("Simulated reserve, {line}", line=_line_name(r["segment"], r["line"])),
            t("Reserve ({currency})", currency=currency),
            t("Simulations"),
            height=260,
            xaxis={
                "title": {"text": t("Reserve ({currency})", currency=currency)},
                "range": [
                    _round(low),
                    _round(high),
                ],
            },
        )
        layout["shapes"] = [
            {
                "type": "line",
                "x0": _round(x),
                "x1": _round(x),
                "yref": "paper",
                "y0": 0,
                "y1": 1,
                "line": {"color": INK if dash == "solid" else MUTED, "dash": dash, "width": 1.5},
            }
            for x, _, dash in shown
        ]
        layout["annotations"] = [
            {
                "x": _round(x),
                "y": 1,
                "yref": "paper",
                "text": name,
                "showarrow": False,
                "yanchor": "bottom",
                "font": {"size": 10},
            }
            for x, name, _ in shown
        ]
        figure = {
            "data": [
                {
                    "type": "bar",
                    "x": [_round(float(c)) for c in centres],
                    "y": [int(c) for c in counts],
                    "marker": {"color": basis_colour(basis)},
                    "hovertemplate": t(
                        "%{x:,.0f} {currency}: %{y} simulations<extra></extra>", currency=currency
                    ),
                }
            ],
            "layout": layout,
        }
        out.append((f"{r['segment']}-{r['line']}", figure, caption))
    return out


def cash_flows(frame: pl.DataFrame, discounted: bool) -> list[dict[str, Any]]:
    """Expected cash flows of all lines by calendar period: nominal, and discounted with the
    discount factor of the period when a curve is used."""
    if not frame.height:
        return []
    summed = (
        frame.group_by("period", maintain_order=True)
        .agg(
            pl.col("payment_date").first(),
            pl.col("years").first(),
            pl.col("discount_factor").first(),
            pl.col("expected_nominal").sum(),
            pl.col("expected_discounted").sum(),
        )
        .sort("period")
        .filter(pl.col("expected_nominal").abs() > 0)
    )
    return [
        {
            "period": numbers.count(value(r["period"])),
            "date": r["payment_date"].isoformat() if r["payment_date"] else "",
            "factor": numbers.factor(value(r["discount_factor"])) if discounted else numbers.EMPTY,
            "nominal": numbers.amount(value(r["expected_nominal"])),
            "discounted": numbers.amount(value(r["expected_discounted"]))
            if discounted
            else numbers.EMPTY,
        }
        for r in summed.to_dicts()
    ]


def cash_flow_figure(frame: pl.DataFrame, discounted: bool, currency: str) -> dict[str, Any] | None:
    rows = cash_flows(frame, discounted)
    if not rows:
        return None
    summed = (
        frame.group_by("period", maintain_order=True)
        .agg(pl.col("expected_nominal").sum(), pl.col("expected_discounted").sum())
        .sort("period")
        .filter(pl.col("expected_nominal").abs() > 0)
    )
    periods = [str(int(p)) for p in summed["period"]]
    data = [
        {
            "type": "bar",
            "name": t("nominal"),
            "x": periods,
            "y": [_round(value(v)) for v in summed["expected_nominal"]],
            "marker": {"color": basis_colour(NOMINAL)},
            "hovertemplate": t("nominal: %{y:,.0f} {currency}<extra></extra>", currency=currency),
        }
    ]
    if discounted:
        data.append(
            {
                "type": "bar",
                "name": t("present value"),
                "x": periods,
                "y": [_round(value(v)) for v in summed["expected_discounted"]],
                "marker": {"color": basis_colour(DISCOUNTED)},
                "hovertemplate": t(
                    "present value: %{y:,.0f} {currency}<extra></extra>", currency=currency
                ),
            }
        )
    return {
        "data": data,
        "layout": _layout(
            t("Expected payments of all lines by future period, {currency}", currency=currency),
            t("Period after the valuation date"),
            t("Payments ({currency})", currency=currency),
            xaxis={"title": {"text": t("Period after the valuation date")}, "type": "category"},
            barmode="group",
            showlegend=discounted,
            height=280,
        ),
    }


def curve(result: UncertaintyResult, frame: pl.DataFrame) -> dict[str, Any] | None:
    found = result.discount.curve
    if found is None:
        return None
    inputs = found.input_rates()
    if found.rate_type == "PAR":
        kind = t("par rate, annual coupons")
    elif found.rate_type == "FORWARD":
        kind = t("one-year forward rate, annually compounded")
    else:
        kind = t("spot rate, {compounding}", compounding=found.compounding)
    return {
        "input_heading": t("Input rate ({kind})", kind=kind),
        "rows": [
            (t("Curve"), found.curve_id),
            (t("Curve date"), found.curve_date.isoformat()),
            (t("Currency"), found.currency),
            (t("Rate type"), found.rate_type),
            (t("Compounding of the input rate"), found.compounding),
            (t("Source"), found.source or numbers.EMPTY),
            (t("Discount date"), result.discount.discount_date.isoformat()),
            (t("Payment timing"), t(result.discount.timing.value.replace("_", " "))),
            (t("Years of the tail payments"), str(result.discount.tail_payment_years)),
        ],
        "points": [
            {
                "tenor": numbers.factor(value(r["tenor_years"])),
                "input": numbers.ratio(float(inputs[i])),
                "zero": numbers.ratio(value(r["zero_rate"])),
                "factor": numbers.factor(value(r["discount_factor"])),
                "forward": numbers.ratio(value(r["forward_rate"])),
            }
            for i, r in enumerate(frame.to_dicts())
        ],
    }


def statements(result: UncertaintyResult) -> dict[str, Any]:
    """What the totals rest on (records 0323 and 0325): the line correlation, the TVaR
    estimator, the simulations and the tail count, and when an all-lines simulation exists."""
    risk = result.risk
    boot = [r for r in _totals(risk) if r["source"] == BOOTSTRAP_SOURCE]
    mack = [r for r in _totals(risk) if r["source"] == MACK_SOURCE]
    simulated = sorted(
        {_line_name(r["segment"], r["line"]) for r in boot if r["segment"] != ALL_LINES}
    )
    lines = sorted(
        {_line_name(r["segment"], r["line"]) for r in _totals(risk) if r["segment"] != ALL_LINES}
    )
    total = any(r["segment"] == ALL_LINES for r in boot)
    first = boot[0] if boot else None
    cut = [
        f"{_line_name(*x.key)}: {x.boot.columns_cut}"
        for x in result.lines
        if x.boot is not None and x.boot.cut_columns
    ]
    return {
        "cut": ", ".join(cut),
        "correlation": numbers.factor(result.correlation),
        "independent": result.correlation == 0,
        "boot_estimator": text(first["estimator"]) if first else "",
        "mack_estimator": text(mack[0]["estimator"]) if mack else "",
        "simulations": numbers.count(value(first["simulations"])) if first else "",
        "tail_count": numbers.count(value(first["tail_count"])) if first else "",
        "tvar_level": numbers.ratio(value(first["tvar_level"])) if first else "",
        "simulated": simulated,
        "lines": len(lines),
        "all_lines_total": total,
    }


def _share(part: float | None, whole: float | None) -> float | None:
    return part / whole if part is not None and whole else None


def calibration(tables: Mapping[str, pl.DataFrame]) -> list[dict[str, Any]]:
    """The share of later outcomes inside the ranges of earlier valuations (AE02 range
    calibration of back_test.csv), summed over the lines per method and horizon."""
    frame = table(tables, tier_b_output.BACK_TEST_NAME)
    if not frame.height:
        return []
    found = frame.filter(pl.col("kind") == "range_calibration")
    if not found.height:
        return []
    summed = (
        found.group_by("method", "horizon_months")
        .agg(pl.col("origins").sum(), pl.col("inside").sum(), pl.len().alias("lines"))
        .sort("method", "horizon_months")
    )
    return [
        {
            "method": r["method"],
            "horizon": numbers.count(value(r["horizon_months"])),
            "lines": numbers.count(value(r["lines"])),
            "origins": numbers.count(value(r["origins"])),
            "share": numbers.ratio(_share(value(r["inside"]), value(r["origins"]))),
        }
        for r in summed.to_dicts()
    ]


def tail_effects(tables: Mapping[str, pl.DataFrame]) -> list[dict[str, Any]]:
    frame = table(tables, "sensitivity.csv")
    if not frame.height:
        return []
    return [
        {
            "line": f"{r['segment']} · {r['line']}",
            "base": numbers.amount(value(r["base"])),
            "value": numbers.amount(value(r["value"])),
            "change": numbers.change_ratio(value(r["relative"])),
            "note": text(r["note"]),
        }
        for r in frame.filter(pl.col("variant") == "tail_fitted").to_dicts()
    ]


def uncertainty_page(
    uncertainty: UncertaintyResult | str | None,
    tables: Mapping[str, pl.DataFrame],
    spec: Callable[..., str],
    figures: dict[str, Any],
    currency: str,
) -> dict[str, Any]:
    if not isinstance(uncertainty, UncertaintyResult):
        return {"reason": uncertainty or t("M12 did not run"), "bases": []}
    discounted = uncertainty.discount.available
    bases = [NOMINAL, DISCOUNTED] if discounted else [NOMINAL]
    blocks = []
    for basis in bases:
        range_id = f"uncertainty-range-{basis.lower()}"
        found = range_figure(uncertainty.risk, basis, currency, tables)
        if found is not None:
            figures[range_id] = found
        histograms = []
        for key, figure, caption in histogram(
            uncertainty.risk, uncertainty.distribution, basis, currency
        ):
            figure_id = f"uncertainty-histogram-{basis.lower()}-{key}".replace(" ", "-").replace(
                "/", "-"
            )
            figures[figure_id] = figure
            histograms.append({"id": figure_id, "caption": caption})
        blocks.append(
            {
                "basis": basis,
                "label": t("present value") if basis == DISCOUNTED else t("nominal"),
                "headline": headline(
                    uncertainty.risk,
                    uncertainty.distribution,
                    basis,
                    selected_totals(uncertainty.lines),
                    tables,
                ),
                "present_values": present_values(uncertainty.risk) if basis == DISCOUNTED else [],
                "bridge": bridge_table(uncertainty, basis),
                "ranges": ranges(uncertainty.risk, basis, tables),
                "range_figure": range_id if found is not None else "",
                "histograms": histograms,
            }
        )
    flows_id = "uncertainty-cash-flows"
    flows = cash_flow_figure(uncertainty.cash_flows, discounted, currency)
    if flows is not None:
        figures[flows_id] = flows
    return {
        "reason": "",
        "bases": bases,
        "blocks": blocks,
        "cash_flows": cash_flows(uncertainty.cash_flows, discounted),
        "cash_flow_figure": flows_id if flows is not None else "",
        "discounted": discounted,
        "discount_reason": "" if discounted else uncertainty.discount.reason,
        "curve": curve(uncertainty, uncertainty.curve),
        "statements": statements(uncertainty),
        "calibration": calibration(tables),
        "tail_effects": tail_effects(tables),
        "notes": list(uncertainty.notes),
        "footnotes": {
            "headline": t(
                "The selected unpaid (RS02 with MT10) is the one total of the run; the mean of "
                "the range is the mean of M12's simulation: the bootstrap ({rs05}) where it ran "
                "on the line, else the Mack approximation ({rs03}). The two differ by the steps "
                "of the table below the ranges. The 5th percentile comes from "
                "risk_distribution.parquet or the lognormal of RS03. Indicative ranges, never "
                "capital requirements.",
                rs05=spec("RS05", "MT11"),
                rs03=spec("RS03", "MT06"),
            ),
            "present_values": t(
                "Rows expected_cash_flows of risk_measures.csv ({specs}): the selected unpaid "
                "less its discount effect is its present value. The simulated means in the "
                "table above are of the simulation, not of these cash flows, so the two "
                "discount effects differ.",
                specs=spec("RS04", "CV10"),
            ),
            "bridge": t(
                "An origin that is fully developed in the simulated triangle carries no "
                "simulated development and keeps zero in the simulation (records 0325, 0349), "
                "although its selected unpaid is not zero; its selected unpaid is left out of "
                "the simulated mean and listed. The remaining difference is the mean of the "
                "simulation for the other origins less their selected unpaid: zero where the "
                "simulation is scaled to the selected unpaid, sampling difference otherwise. "
                "Rows add up before rounding."
            ),
            "ranges": t(
                "Rows Total and All lines of risk_measures.csv ({specs}). VaR at 99.5% and "
                "TVaR at 99%; both sources are approximations of the uncertainty of the "
                "selected reserve, labelled as such in the file.",
                specs=spec("RS03", "RS05", "M12"),
            ),
            "figure": t(
                "Ranges drawn as ranges: light bar from the median to the 99.5th percentile, "
                "dark bar from the 75th to the 95th, the mean as a diamond."
            ),
            "histogram": t(
                "Histogram of the simulated reserve ({spec}); the lines mark the mean, the "
                "VaR and the TVaR of the row in risk_measures.csv; simulations in "
                "risk_distribution.parquet, which holds all of them. The axis is cut at the "
                "0.5th and 99.5th percentile so that a few extreme draws do not hide the shape; "
                "the caption of each histogram gives the extremes.",
                spec=spec("RS05"),
            ),
            "cash_flows": t(
                "Expected payments of the selected unpaid by period after the valuation date, "
                "all lines added ({specs}); rows of risk_cash_flows.csv.",
                specs=spec("RS04", "CV10"),
            ),
            "calibration": t(
                "Share of the incurred known later that fell inside the range given at an "
                "earlier valuation, summed over the lines (AE02 rows of back_test.csv, {spec}). "
                "Coverage on model data is in records 0075 (Mack), 0282 (bootstrap) and 0325 "
                "(this module); Mack ranges are known to be too narrow on inflation-driven or "
                "long-tailed lines (record 0062).",
                spec=spec("MT22", "AE02"),
            ),
        },
    }


__all__ = ["BASES", "basis_colour", "uncertainty_page"]
