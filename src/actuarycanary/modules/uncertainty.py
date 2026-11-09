"""Uncertainty and risk (M12): the reserve range of each line from the Mack lognormal (RS03) and
from the bootstrap (RS05), the expected cash flows of the selected unpaid and their present value
(RS04, CV10), and the lines added to a total.

Everything is computed from results the reserving module already has: the Mack standard errors,
the selection, the paid chain ladder with its fitted tail and the MT11 simulations. Nothing here
draws from the bootstrap again; the only random draw is the reordering that gives the lines a
correlation (`measures.risk.add_lines`), and it is off at the default correlation 0.

Records 0323 to 0329 give the choices: the simulated reserve of an origin is scaled to the
selected unpaid when the selection is not the chain-ladder reserve; the discounted distribution
exists for a line and for all lines because MT11 keeps no cash flows by origin; the expected
pattern is the paid chain-ladder pattern scaled to the selected unpaid of each origin.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.convert.discount import DiscountContext
from actuarycanary.measures.risk import (
    ESTIMATOR,
    LOGNORMAL_ESTIMATOR,
    SampleRisk,
    add_lines,
    combined_standard_error,
    lognormal_risk,
    sample_risk,
)
from actuarycanary.methods.assumptions import (
    ANY_SCOPE,
    DEFAULT_WHO,
    Assumption,
    AssumptionError,
    AssumptionsRegister,
)
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.inflation_adjusted import cash_flow_periods
from actuarycanary.methods.mack import PERCENTILES, TVAR_LEVEL, VAR_LEVEL, Mack
from actuarycanary.methods.odp_bootstrap import OdpBootstrap
from actuarycanary.methods.seeding import RUN_SEED
from actuarycanary.methods.selection import Selection
from actuarycanary.methods.tail import CurveFit, TailFit
from actuarycanary.modules.reserving import GroupReserving, ReservingResult

ALL_LINES = "All lines"
TOTAL = "Total"
LINE_CORRELATION = "line_correlation"
RS05 = "RS05"
SAME_RESERVE = 1e-9  # a selected reserve this close (relative) to the chain ladder's is its
ZERO_RESERVE = 1e-12
TAIL_SHARE_FLOOR = 1e-9  # trailing tail periods adding less than this share are folded back
PERCENTILE_COLUMNS = {0.5: "p50", 0.75: "p75", 0.9: "p90", 0.95: "p95", 0.99: "p99", 0.995: "p99_5"}
NOMINAL, DISCOUNTED = "NOMINAL", "DISCOUNTED"
MACK_SOURCE, BOOTSTRAP_SOURCE, EXPECTED_SOURCE = (
    "mack_lognormal",
    "bootstrap",
    "expected_cash_flows",
)
BOOTSTRAP_LABEL = "bootstrap (over-dispersed Poisson, MT11)"
SHIFTED_LABEL = "bootstrap CV applied to the selected reserve"
MACK_LABEL = "approximation: Mack standard error with lognormal assumption"
MACK_SELECTED_LABEL = (
    "approximation: Mack coefficient of variation applied to the selected reserve, "
    "lognormal assumption"
)

RISK_COLUMNS = (
    "segment", "line", "origin_period", "source", "value_basis", "mean", "standard_deviation",
    "coefficient_of_variation", "p50", "p75", "p90", "p95", "p99", "p99_5", "var_level",
    "value_at_risk", "tvar_level", "tail_value_at_risk", "estimator", "simulations",
    "tail_count", "negative_share", "nominal_mean", "discount_effect", "label", "note",
)  # fmt: skip
TEXT_COLUMNS = (
    "segment", "line", "origin_period", "source", "value_basis", "estimator", "label", "note",
)  # fmt: skip
CASH_FLOW_COLUMNS = (
    "segment", "line", "period", "start", "end", "payment_date", "years", "discount_factor",
    "expected_nominal", "expected_discounted", "bootstrap_mean", "bootstrap_p50",
    "bootstrap_p95", "bootstrap_p99_5", "discounted_mean", "discounted_p50", "discounted_p95",
    "discounted_p99_5", "note",
)  # fmt: skip


@dataclass(frozen=True)
class LineRisk:
    """One line (segment and line): its range on both sources and its expected cash flows."""

    key: tuple[str, str]
    origins: tuple[str, ...]
    selected_unpaid: np.ndarray  # per origin
    selection_label: str  # where the selected unpaid comes from
    mack_cv: np.ndarray | None  # per origin
    mack_total_cv: float | None
    notes: tuple[str, ...]
    mack_same: bool = True  # the selected unpaid is the Mack reserve, so the Mack figures stand
    boot: OdpBootstrap | None = None
    shifted: bool = False
    origin_sims: np.ndarray | None = None  # simulations x origins, scaled
    total_sims: np.ndarray | None = None
    cash_flow_sims: np.ndarray | None = None  # simulations x periods, scaled
    flows: np.ndarray | None = None  # origins x periods, expected nominal
    flow_notes: tuple[str, ...] = ()
    periods: tuple[tuple[date, date], ...] = ()
    discounted_sims: np.ndarray | None = None
    discount_factors: np.ndarray | None = None  # per period
    payment_dates: tuple[date, ...] = ()
    cut_note: str = ""  # MT11 fitted on a triangle cut after its last positive column (0349)

    @property
    def selected_total(self) -> float:
        return float(np.nansum(self.selected_unpaid))


@dataclass(frozen=True)
class UncertaintyResult:
    """Everything M12 shows and writes."""

    lines: tuple[LineRisk, ...]
    discount: DiscountContext
    correlation: float
    risk: pl.DataFrame  # RISK_COLUMNS, RS03 and RS05 and the expected pattern
    cash_flows: pl.DataFrame  # CASH_FLOW_COLUMNS
    distribution: pl.DataFrame  # one row per simulation
    curve: pl.DataFrame  # the points of the curve, empty without one
    notes: tuple[str, ...] = ()
    reasons: dict[str, str] = field(default_factory=dict)  # measure -> why it is not available


def line_correlation(register: AssumptionsRegister) -> tuple[float, Assumption]:
    """The correlation between lines of an all-lines total (RS05) and its register entry."""
    user = register.find(RS05, LINE_CORRELATION, ANY_SCOPE).get("")
    if user is None:
        return 0.0, Assumption(
            method=RS05,
            name=LINE_CORRELATION,
            value=0.0,
            default=0.0,
            who=DEFAULT_WHO,
            why="independence between lines, the sum of independent reserves",
        )
    value = user.value
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
        raise AssumptionError(f"{RS05} {LINE_CORRELATION}: {value!r} is not a number from 0 to 1")
    return float(value), Assumption(
        method=RS05, name=LINE_CORRELATION, value=float(value), default=0.0,
        who=user.who, when=user.when, why=user.why,
    )  # fmt: skip


# --- one line ---------------------------------------------------------------------------------


def _selected_unpaid(group: GroupReserving) -> tuple[np.ndarray, str] | None:
    """The selected unpaid per origin (selected ultimate minus paid, RS02), else the paid chain
    ladder reserve; None when neither exists."""
    paid = group.triangles["paid"].latest
    if isinstance(group.selection, Selection):
        return group.selection.ultimate - paid, "selected ultimate (MT10) minus paid"
    chain = group.chain_ladder.get("paid")
    if isinstance(chain, ChainLadder):
        return chain.reserve, "paid chain ladder (no ultimate was selected)"
    return None


def _pattern(
    chain: ChainLadder,
    tail: TailFit | Skipped | None,
    tail_periods: int,
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    """Expected incremental payments of each origin by future calendar period (origins x
    periods) following the paid chain-ladder pattern, and the tail weights over the periods
    after the triangle (CV10). Returns (flows, tail_weights, notes); flows hold the pattern
    for the nominal chain-ladder reserve and still need scaling to the selected unpaid."""
    n_dev = len(chain.cdf)
    n_origins = len(chain.latest)
    last = chain.latest_index
    fit = None
    notes: list[str] = []
    weights = np.full(tail_periods, 1.0 / tail_periods)
    if tail is not None and not isinstance(tail, Skipped):
        chosen = tail.chosen
        if isinstance(chosen, CurveFit) and np.isclose(chosen.tail_factor, chain.tail_factor):
            fit = chosen
    if fit is not None:
        share = np.asarray(fit.extension_share, dtype=float)
        keep = int(np.nonzero(share > TAIL_SHARE_FLOOR * share.sum())[0].max()) + 1
        weights = share[:keep] / share[:keep].sum()
        notes.append("tail flows follow the fitted tail curve (MT14)")
    elif chain.tail_factor != 1:
        notes.append(f"tail spread evenly over {tail_periods} periods")
    n_tail = len(weights) if chain.tail_factor != 1 else 0
    periods = int((n_dev - 1 - last).max()) + n_tail
    flows = np.zeros((n_origins, max(periods, 0)))
    for i in range(n_origins):
        ultimate = float(chain.latest[i] * chain.cdf[last[i]])
        for k in range(int(last[i]) + 1, n_dev):
            flows[i, k - int(last[i]) - 1] = ultimate * (1 / chain.cdf[k] - 1 / chain.cdf[k - 1])
        if n_tail:
            start = n_dev - 1 - int(last[i])
            amount = ultimate * (1 - 1 / chain.cdf[n_dev - 1])
            flows[i, start : start + n_tail] += amount * weights
    return flows, weights, tuple(notes)


def _scaled_flows(
    flows: np.ndarray, selected: np.ndarray, origins: Sequence[str]
) -> tuple[np.ndarray, tuple[str, ...]]:
    """The pattern scaled so that each origin's flows add to its selected unpaid (RS04)."""
    scaled = np.zeros_like(flows)
    notes: list[str] = []
    for i, origin in enumerate(origins):
        total = float(flows[i].sum())
        if abs(total) > ZERO_RESERVE * max(1.0, abs(selected[i])):
            scaled[i] = flows[i] * (selected[i] / total)
        elif abs(selected[i]) > ZERO_RESERVE and flows.shape[1]:
            scaled[i, 0] = selected[i]
            notes.append(
                f"origin {origin}: no chain-ladder pattern left, the unpaid falls in period 1"
            )
        if selected[i] < 0:
            notes.append(
                f"origin {origin}: negative selected unpaid, discounted like any cash flow"
            )
    return scaled, tuple(notes)


def _discount_ratio(cash_flows: np.ndarray, factors: np.ndarray) -> np.ndarray:
    """Per simulation, the share of its reserve that is left after discounting: the discounted
    over the nominal simulated cash flows (MT11 keeps them by calendar period, CV10). It is
    applied to the reserve as scaled to the selected unpaid, so that without discounting the two
    distributions are the same. A simulation whose cash flows do not add to a positive amount
    takes the ratio of the means, and no ratio leaves the range of the factors."""
    n_periods = cash_flows.shape[1]
    weights = np.concatenate([factors, np.full(max(n_periods - len(factors), 0), factors[-1])])
    weights = weights[:n_periods]
    present = cash_flows @ weights
    total = cash_flows.sum(axis=1)
    mean_total = float(total.mean())
    fallback = float(present.mean()) / mean_total if mean_total else 1.0
    safe = np.where(total > 0, total, 1.0)
    ratio = np.where(total > 0, present / safe, fallback)
    return np.clip(ratio, weights.min(), weights.max())


def _line(
    group: GroupReserving,
    discount: DiscountContext,
    cut_off: date,
    development_months: int,
) -> LineRisk | tuple[tuple[str, str], str]:
    """The risk of one line, or (key, reason) when it has nothing to show."""
    key = (group.group[0], group.group[1])
    picked = _selected_unpaid(group)
    if picked is None:
        return key, "the paid chain ladder did not run, so there is no selected unpaid"
    selected, label = picked
    origins = tuple(group.triangles["paid"].origins)
    mack = group.mack.get("paid")
    notes: list[str] = []
    chain = group.chain_ladder.get("paid")
    mack_cv = mack_total = None
    mack_same = False
    if isinstance(mack, Mack):
        mack_cv, mack_total = mack.coefficient_of_variation, mack.total_coefficient_of_variation
        mack_same = bool(np.allclose(selected, mack.reserve, rtol=SAME_RESERVE, atol=0))
    else:
        notes.append("MT06 did not run: no Mack range")
    boot = group.tier_b.bootstrap if group.tier_b is not None else None
    if not isinstance(boot, OdpBootstrap):
        reason = boot.reason if isinstance(boot, Skipped) else "MT11 did not run"
        notes.append(f"{reason}: no bootstrap range")
        boot = None
    cut_note = ""
    if boot is not None and boot.cut_columns:
        cut_note = boot.cut_note(group.triangles["paid"].ages)
        notes.append(f"bootstrap {cut_note}")
    line = LineRisk(key, origins, selected, label, mack_cv, mack_total, tuple(notes), mack_same)
    if not isinstance(chain, ChainLadder):
        return line
    development_years = development_months / 12
    tail_periods = max(1, round(discount.tail_payment_years / development_years))
    tail = group.tier_b.tails.get("paid") if group.tier_b is not None else None
    pattern, _, flow_notes = _pattern(chain, tail, tail_periods)
    flows, scale_notes = _scaled_flows(pattern, selected, origins)
    periods = tuple(cash_flow_periods(cut_off, development_months, flows.shape[1]))
    dates = tuple(discount.payment_date(start, end) for start, end in periods)
    factors = discount.factors(list(dates)) if discount.available and dates else None
    line = LineRisk(
        key, origins, selected, label, mack_cv, mack_total, tuple(notes), mack_same,
        flows=flows, flow_notes=(*flow_notes, *scale_notes), periods=periods,
        discount_factors=factors, payment_dates=dates,
    )  # fmt: skip
    if boot is None:
        return line
    reserves = boot.reserves
    n = reserves.shape[0]
    same = np.allclose(selected, chain.reserve, rtol=SAME_RESERVE, atol=0)
    factor = np.ones(reserves.shape[1])
    shifted = not same
    if shifted:
        mean = reserves.mean(axis=0)
        movable = np.abs(mean) > ZERO_RESERVE
        factor = np.where(movable, selected / np.where(movable, mean, 1.0), 1.0)
        for i in np.nonzero(~movable & (np.abs(selected) > ZERO_RESERVE))[0]:
            notes.append(f"origin {origins[i]}: no simulated unpaid to scale to the selected one")
    origin_sims = reserves * factor
    total_sims = origin_sims.sum(axis=1)
    base = float(reserves.sum(axis=1).mean())
    ratio = float(total_sims.mean()) / base if base else 1.0
    cash_sims = boot.cash_flows * ratio
    discounted = None
    if factors is not None and boot.cash_flows.shape[1]:
        discounted = total_sims * _discount_ratio(boot.cash_flows, factors)
    if n != total_sims.size:
        raise ValueError("simulations of a line disagree")
    return LineRisk(
        key, origins, selected, label, mack_cv, mack_total, tuple(notes), mack_same,
        boot=boot, shifted=shifted, origin_sims=origin_sims, total_sims=total_sims,
        cash_flow_sims=cash_sims, flows=flows, flow_notes=line.flow_notes, periods=periods,
        discounted_sims=discounted, discount_factors=factors, payment_dates=dates,
        cut_note=cut_note,
    )  # fmt: skip


# --- tables -----------------------------------------------------------------------------------


def _sample_row(
    base: dict[str, Any],
    risk: SampleRisk,
    basis: str,
    label: str,
    nominal_mean: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    row = {
        **base, "source": BOOTSTRAP_SOURCE, "value_basis": basis, "mean": risk.mean,
        "standard_deviation": risk.standard_deviation,
        "coefficient_of_variation": risk.coefficient_of_variation,
        "var_level": risk.var_level, "value_at_risk": risk.value_at_risk,
        "tvar_level": risk.tvar_level, "tail_value_at_risk": risk.tail_value_at_risk,
        "estimator": ESTIMATOR, "simulations": float(risk.count),
        "tail_count": float(risk.tail_count), "negative_share": risk.negative_share,
        "label": label, "note": note,
    }  # fmt: skip
    row |= {
        PERCENTILE_COLUMNS[p]: v for p, v in risk.percentiles.items() if p in PERCENTILE_COLUMNS
    }
    if nominal_mean is not None:
        row |= {"nominal_mean": nominal_mean, "discount_effect": nominal_mean - risk.mean}
    return row


def _mack_row(base: dict[str, Any], mean: float, se: float, label: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        **base, "source": MACK_SOURCE, "value_basis": NOMINAL, "mean": mean,
        "standard_deviation": se, "estimator": LOGNORMAL_ESTIMATOR, "label": label,
    }  # fmt: skip
    if mean:
        row["coefficient_of_variation"] = se / mean
    shown = lognormal_risk(mean, se, PERCENTILES, VAR_LEVEL, TVAR_LEVEL)
    if shown is None:
        row["note"] = "range not shown: the reserve is not positive or the standard error is zero"
        return row
    row |= {
        PERCENTILE_COLUMNS[p]: v for p, v in shown.percentiles.items() if p in PERCENTILE_COLUMNS
    }
    row |= {
        "var_level": shown.var_level, "value_at_risk": shown.value_at_risk,
        "tvar_level": shown.tvar_level, "tail_value_at_risk": shown.tail_value_at_risk,
    }  # fmt: skip
    return row


def _expected_row(
    base: dict[str, Any], nominal: float, present: float, curve_note: str
) -> dict[str, Any]:
    return {
        **base, "source": EXPECTED_SOURCE, "value_basis": DISCOUNTED, "mean": present,
        "nominal_mean": nominal, "discount_effect": nominal - present,
        "label": "expected cash flows of the selected unpaid, discounted (RS04)",
        "note": curve_note,
    }  # fmt: skip


def _frame(
    rows: list[dict[str, Any]],
    columns: Sequence[str],
    text: Sequence[str],
    dates: Sequence[str] = (),
) -> pl.DataFrame:
    schema: dict[str, Any] = {
        c: pl.String if c in text else pl.Date if c in dates else pl.Float64 for c in columns
    }
    return pl.DataFrame(rows, schema=schema, infer_schema_length=None).select(*columns)


def _risk_rows(
    lines: Sequence[LineRisk],
    discount: DiscountContext,
    correlation: float,
    total_sims: np.ndarray | None,
    total_discounted: np.ndarray | None,
) -> list[dict[str, Any]]:
    levels = (tuple(PERCENTILE_COLUMNS), VAR_LEVEL, TVAR_LEVEL)
    rows: list[dict[str, Any]] = []
    curve_note = (
        f"curve {discount.curve.curve_id} of {discount.curve.curve_date}" if discount.curve else ""
    )
    for line in lines:
        segment, name = line.key

        def base(origin: str, _s: str = segment, _n: str = name) -> dict[str, Any]:
            return {"segment": _s, "line": _n, "origin_period": origin}

        selected_label = MACK_LABEL if line.mack_same else MACK_SELECTED_LABEL
        if line.mack_cv is not None and line.mack_total_cv is not None:
            for i, origin in enumerate(line.origins):
                rows.append(
                    _mack_row(base(origin), float(line.selected_unpaid[i]),
                              float(line.mack_cv[i] * line.selected_unpaid[i]), selected_label)
                )  # fmt: skip
            rows.append(
                _mack_row(base(TOTAL), line.selected_total,
                          float(line.mack_total_cv * line.selected_total), selected_label)
            )  # fmt: skip
        if line.origin_sims is not None and line.total_sims is not None:
            label = SHIFTED_LABEL if line.shifted else BOOTSTRAP_LABEL
            for i, origin in enumerate(line.origins):
                rows.append(
                    _sample_row(
                        base(origin), sample_risk(line.origin_sims[:, i], *levels), NOMINAL, label
                    )
                )
            rows.append(
                _sample_row(
                    base(TOTAL), sample_risk(line.total_sims, *levels), NOMINAL, label,
                    note=line.cut_note,
                )
            )  # fmt: skip
            if line.discounted_sims is not None:
                risk = sample_risk(line.discounted_sims, *levels)
                nominal_mean = float(line.total_sims.mean())
                rows.append(
                    _sample_row(base(TOTAL), risk, DISCOUNTED, label, nominal_mean, curve_note)
                )
        if line.flows is not None and line.discount_factors is not None:
            present = line.flows @ line.discount_factors
            for i, origin in enumerate(line.origins):
                rows.append(
                    _expected_row(
                        base(origin), float(line.selected_unpaid[i]), float(present[i]), curve_note
                    )
                )
            rows.append(
                _expected_row(base(TOTAL), line.selected_total, float(present.sum()), curve_note)
            )
    # all lines
    base_all = {"segment": ALL_LINES, "line": ALL_LINES, "origin_period": TOTAL}
    with_mack = [x for x in lines if x.mack_total_cv is not None]
    if len(lines) > 1 and with_mack and len(with_mack) == len(lines):
        mean = sum(x.selected_total for x in lines)
        se = combined_standard_error(
            [float(x.mack_total_cv or 0.0) * x.selected_total for x in lines], correlation
        )
        rows.append(
            _mack_row(
                base_all, mean, se, f"{MACK_SELECTED_LABEL}; line correlation {correlation:g}"
            )
        )
    if total_sims is not None:
        label = f"{BOOTSTRAP_LABEL}; lines added with correlation {correlation:g}"
        rows.append(_sample_row(base_all, sample_risk(total_sims, *levels), NOMINAL, label))
        if total_discounted is not None:
            rows.append(
                _sample_row(base_all, sample_risk(total_discounted, *levels), DISCOUNTED, label,
                            float(total_sims.mean()), curve_note)
            )  # fmt: skip
    expected = [x for x in lines if x.flows is not None and x.discount_factors is not None]
    if len(lines) > 1 and expected and len(expected) == len(lines):
        nominal = sum(x.selected_total for x in lines)
        present = sum(float((x.flows @ x.discount_factors).sum()) for x in expected)  # type: ignore[operator]
        rows.append(_expected_row(base_all, nominal, present, curve_note))
    return rows


def _cash_flow_rows(lines: Sequence[LineRisk], discount: DiscountContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        if line.flows is None:
            continue
        factors = line.discount_factors
        beyond = discount.beyond_curve(list(line.payment_dates)) if factors is not None else 0
        for s, (start, end) in enumerate(line.periods):
            row: dict[str, Any] = {
                "segment": line.key[0], "line": line.key[1], "period": float(s + 1),
                "start": start, "end": end, "payment_date": line.payment_dates[s],
                "years": float(discount.years([line.payment_dates[s]])[0]),
                "expected_nominal": float(line.flows[:, s].sum()), "note": "",
            }  # fmt: skip
            if factors is not None:
                row["discount_factor"] = float(factors[s])
                row["expected_discounted"] = float(line.flows[:, s].sum() * factors[s])
                if s == 0 and beyond:
                    row["note"] = (
                        f"{beyond} periods lie beyond the curve: last forward rate held flat"
                    )
            if line.cash_flow_sims is not None and s < line.cash_flow_sims.shape[1]:
                column = line.cash_flow_sims[:, s]
                row |= {
                    "bootstrap_mean": float(column.mean()),
                    "bootstrap_p50": float(np.quantile(column, 0.5)),
                    "bootstrap_p95": float(np.quantile(column, 0.95)),
                    "bootstrap_p99_5": float(np.quantile(column, 0.995)),
                }
                if factors is not None:
                    row |= {
                        "discounted_mean": row["bootstrap_mean"] * float(factors[s]),
                        "discounted_p50": row["bootstrap_p50"] * float(factors[s]),
                        "discounted_p95": row["bootstrap_p95"] * float(factors[s]),
                        "discounted_p99_5": row["bootstrap_p99_5"] * float(factors[s]),
                    }
            rows.append(row)
    return rows


def run_uncertainty(
    reserving: ReservingResult,
    discount: DiscountContext,
    register: AssumptionsRegister,
    seed: int = RUN_SEED,
) -> UncertaintyResult | str:
    """M12 over the groups of the reserving result. The reason (text) when no group has a
    selected unpaid."""
    correlation, entry = line_correlation(register)
    months = reserving.triangles.settings.development_period.months
    lines: list[LineRisk] = []
    reasons: list[str] = []
    for group in reserving.groups:
        found = _line(group, discount, reserving.triangles.cut_off, months)
        if isinstance(found, LineRisk):
            lines.append(found)
        else:
            reasons.append(f"{' / '.join(found[0])}: {found[1]}")
    if not lines:
        return "; ".join(reasons) or "no line could be developed"

    simulated = [x for x in lines if x.total_sims is not None]
    sizes = {x.total_sims.size for x in simulated if x.total_sims is not None}
    total_sims = total_discounted = None
    unsimulated = [" / ".join(x.key) for x in lines if x.total_sims is None]
    notes = [*reasons, *(f"{' / '.join(x.key)}: {n}" for x in lines for n in x.notes)]
    if len(lines) > 1 and simulated and unsimulated:
        notes.append(
            "no simulated total of all lines: the bootstrap did not run for "
            + ", ".join(unsimulated)
        )
    elif len(sizes) > 1:
        notes.append(
            "the lines have different numbers of simulations: no simulated total of all lines"
        )
    elif len(lines) > 1 and simulated:
        columns = [x.total_sims for x in simulated if x.total_sims is not None]
        total_sims = add_lines(columns, correlation, seed, "all lines", NOMINAL)
        discounted = [x.discounted_sims for x in simulated]
        if discount.available and all(d is not None for d in discounted):
            total_discounted = add_lines(
                [d for d in discounted if d is not None], correlation, seed, "all lines", DISCOUNTED
            )
    risk = _frame(
        _risk_rows(lines, discount, correlation, total_sims, total_discounted),
        RISK_COLUMNS,
        TEXT_COLUMNS,
    )
    cash = _frame(
        _cash_flow_rows(lines, discount),
        CASH_FLOW_COLUMNS,
        ("segment", "line", "note"),
        ("start", "end", "payment_date"),
    )
    distribution: dict[str, np.ndarray] = {}
    for x in simulated:
        name = " / ".join(x.key)
        if x.total_sims is not None:
            distribution[name] = x.total_sims
        if x.discounted_sims is not None:
            distribution[f"{name} (discounted)"] = x.discounted_sims
    if total_sims is not None:
        distribution[ALL_LINES] = total_sims
    if total_discounted is not None:
        distribution[f"{ALL_LINES} (discounted)"] = total_discounted
    frame = (
        pl.DataFrame(
            {"simulation": np.arange(next(iter(distribution.values())).size), **distribution}
        )
        if distribution
        else pl.DataFrame()
    )
    curve = discount.curve.table() if discount.curve is not None else pl.DataFrame()
    return UncertaintyResult(
        tuple(lines), discount, correlation, risk, cash, frame, curve,
        tuple(notes),
    )  # fmt: skip
