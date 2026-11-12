"""The facts of the finding rules KF27 to KF34 (RP01 1.2.0, record 0345), read from the output
tables of the run and from M12: the Munich chain ladder, the back test of the selection, the
fitted tail and the tail sensitivity, the generalised Pareto shape, the settlement cohorts, the
range of all lines and the discount effect.

A fact that the run could not compute is absent, so a rule naming it does not fire. Thresholds
that belong to a method are read from it (the cohort significance and the least number of
events of a report year from MT19's analysis); the limits that only a rule uses are the named
settings of the rule file (`settings` of RP01), put among the facts by `scoped_facts`.
"""

from collections.abc import Mapping

import polars as pl

from actuarycanary.methods.survival import analysis as survival
from actuarycanary.modules import reserving_tier_b_output as tier_b_output
from actuarycanary.modules.reserving import GroupReserving
from actuarycanary.modules.uncertainty import (
    ALL_LINES,
    BOOTSTRAP_SOURCE,
    DISCOUNTED,
    EXPECTED_SOURCE,
    MACK_SOURCE,
    NOMINAL,
    TOTAL,
    UncertaintyResult,
)
from actuarycanary.report.facts import FactSet, _put, selected_reserve
from actuarycanary.report.frames import of_line, of_segment, value
from actuarycanary.report.sensitivity import SENSITIVITY_NAME, TAIL_STEP

Tables = Mapping[str, pl.DataFrame]


def _table(tables: Tables, name: str) -> pl.DataFrame:
    return tables.get(name, pl.DataFrame())


def add_back_test_facts(facts: FactSet, tables: Tables, segment: str, line: str) -> None:
    """The bias of the selection (MT10) at the first back-test horizon, and the share of the
    back-tested origins whose error has the sign of that bias (KF28)."""
    rows = of_line(_table(tables, tier_b_output.BACK_TEST_NAME), segment, line)
    back = [
        r
        for r in rows
        if r["kind"] == "summary" and r["method"] == "MT10" and value(r["bias"]) is not None
    ]
    if not back:
        return
    first = min(back, key=lambda r: int(r["horizon_months"]))
    bias = float(value(first["bias"]) or 0.0)
    _put(facts, "back_test_bias", bias, "ratio")
    _put(facts, "back_test_bias_size", abs(bias), "ratio")
    _put(facts, "back_test_horizon", value(first["horizon_months"]), "count")
    _put(facts, "back_test_origins", value(first["origins"]), "count")
    errors = [
        value(r["error"])
        for r in rows
        if r["kind"] == "error"
        and r["method"] == "MT10"
        and r["horizon_months"] == first["horizon_months"]
    ]
    known = [e for e in errors if e is not None]
    if known and bias != 0:
        _put(facts, "back_test_sign_share", sum(e * bias > 0 for e in known) / len(known), "ratio")


def add_line_facts(facts: FactSet, tables: Tables, group: GroupReserving) -> None:
    segment, line = group.group[0], group.group[1]
    reserve = selected_reserve(group)

    munich = [
        r
        for r in of_line(_table(tables, tier_b_output.ULTIMATES_NAME), segment, line)
        if r["method"] == "munich_chain_ladder" and r["origin_period"]
    ]
    totals: dict[str, float] = {}
    for measure in ("paid", "incurred"):
        found = [value(r["ultimate"]) for r in munich if r["measure"] == measure]
        if found and all(v is not None for v in found):
            totals[measure] = float(sum(v for v in found if v is not None))
    if len(totals) == 2 and reserve.ultimate:
        _put(facts, "munich_paid", totals["paid"], "amount")
        _put(facts, "munich_incurred", totals["incurred"], "amount")
        gap = totals["incurred"] / reserve.ultimate - 1
        _put(facts, "munich_gap", gap, "ratio")
        _put(facts, "munich_gap_size", abs(gap), "ratio")

    add_back_test_facts(facts, tables, segment, line)

    sensitivity = of_line(_table(tables, SENSITIVITY_NAME), segment, line)
    fitted = next((r for r in sensitivity if r["variant"] == "tail_fitted"), None)
    if fitted is not None and value(fitted["relative"]) is not None:
        _put(facts, "tail_fitted_change", value(fitted["relative"]), "ratio")
        _put(facts, "tail_fitted_ibnr", value(fitted["value"]), "amount")
    _put(facts, "tail_step", TAIL_STEP, "factor")
    raised = next((r for r in sensitivity if r["variant"] == "tail_up"), None)
    if raised is not None and value(raised["relative"]) is not None:
        _put(facts, "tail_up_change", value(raised["relative"]), "ratio")
        _put(facts, "tail_up_ibnr", value(raised["value"]), "amount")
        _put(facts, "tail_up_difference", value(raised["difference"]), "amount")
    chain = group.chain_ladder.get("incurred")
    _put(facts, "tail_factor", getattr(chain, "tail_factor", None), "factor")

    gpd = of_line(_table(tables, "extreme_gpd_fit.csv"), segment, line)
    if gpd:
        _put(facts, "gpd_shape", value(gpd[0]["xi"]), "factor")
        _put(facts, "gpd_threshold", value(gpd[0]["threshold"]), "amount")
        _put(facts, "gpd_exceedances", value(gpd[0]["exceedances"]), "count")


def add_segment_facts(facts: FactSet, tables: Tables, segment: str) -> None:
    cohorts = [
        r
        for r in of_segment(_table(tables, "survival_cohorts.csv"), segment)
        if value(r["logrank_p"]) is not None
    ]
    if cohorts:
        _put(facts, "cohort_logrank_p", value(cohorts[0]["logrank_p"]), "factor")
        _put(
            facts,
            "cohort_years",
            len(of_segment(_table(tables, "survival_cohorts.csv"), segment)),
            "count",
        )
    _put(facts, "cohort_significance", survival.SIGNIFICANCE, "factor")
    years = {
        str(r["report_year"])
        for r in of_segment(_table(tables, "survival_cohorts.csv"), segment)
        if (value(r["events"]) or 0) >= survival.MIN_EVENTS
    }
    year_medians = [
        t
        for r in of_segment(_table(tables, "survival_time_percentiles.csv"), segment)
        if r["grouping"] == "report_year"
        and str(r["group"]) in years
        and value(r["percentile"]) == 0.5
        and (t := value(r["time"])) is not None
        and t > 0
    ]
    if len(year_medians) >= 2:
        _put(facts, "cohort_median_ratio", max(year_medians) / min(year_medians), "factor")
    medians = [
        r
        for r in of_segment(_table(tables, "survival_time_percentiles.csv"), segment)
        if r["grouping"] == "all" and value(r["percentile"]) == 0.5
    ]
    if medians:
        _put(facts, "settlement_median_days", value(medians[0]["time"]), "count")


def add_run_facts(facts: FactSet, uncertainty: UncertaintyResult | str | None) -> None:
    if not isinstance(uncertainty, UncertaintyResult) or not uncertainty.risk.height:
        return
    rows = uncertainty.risk.filter(
        (pl.col("segment") == ALL_LINES) & (pl.col("origin_period") == TOTAL)
    ).to_dicts()
    if not rows and len(uncertainty.lines) == 1:  # one line: its total is the total of all lines
        key = uncertainty.lines[0].key
        rows = uncertainty.risk.filter(
            (pl.col("segment") == key[0])
            & (pl.col("line") == key[1])
            & (pl.col("origin_period") == TOTAL)
        ).to_dicts()
    nominal = [r for r in rows if r["value_basis"] == NOMINAL]
    ranged = next((r for r in nominal if r["source"] == BOOTSTRAP_SOURCE), None) or next(
        (r for r in nominal if r["source"] == MACK_SOURCE), None
    )
    if ranged is not None:
        mean, p95 = value(ranged["mean"]), value(ranged["p95"])
        _put(facts, "range_reserve", mean, "amount")
        _put(facts, "range_p95", p95, "amount")
        _put(facts, "range_source", str(ranged["source"]).replace("_", " "), "text")
        # the one total of the run, called the selected unpaid of all lines (A1a, record 0752)
        _put(facts, "range_selected", sum(x.selected_total for x in uncertainty.lines), "amount")
        if mean and p95 is not None:
            _put(facts, "range_upper_width", p95 / mean - 1, "ratio")
    expected = next(
        (r for r in rows if r["source"] == EXPECTED_SOURCE and r["value_basis"] == DISCOUNTED),
        None,
    )
    curve = uncertainty.discount.curve
    if expected is not None and curve is not None:
        present, before = value(expected["mean"]), value(expected["nominal_mean"])
        _put(facts, "discount_present", present, "amount")
        _put(facts, "discount_nominal", before, "amount")
        _put(facts, "discount_curve", curve.curve_id, "text")
        _put(facts, "discount_curve_date", curve.curve_date.isoformat(), "text")
        if present is not None and before:
            _put(facts, "discount_share", 1 - present / before, "ratio")


__all__ = ["add_back_test_facts", "add_line_facts", "add_run_facts", "add_segment_facts"]
