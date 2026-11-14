"""The finding rules of RP01 (spec/report/findings.yaml): each fires on its condition and only
then, fills its template from facts, and names facts the run computes (decision 0070)."""

import polars as pl
import pytest

from actuarycanary.pipeline import RunResult
from actuarycanary.report.facts import anomaly_rates
from actuarycanary.report.findings import (
    Fact,
    RuleError,
    evaluate,
    facts_named,
    holds,
    parse_condition,
    sentence,
)
from actuarycanary.report.model import scoped_facts
from actuarycanary.report.phase2_facts import add_back_test_facts, add_segment_facts
from actuarycanary.spec.loader import load_specs
from actuarycanary.spec.models import FindingRule

RULES = {r.id: r for r in load_specs().finding_rules.rules}

# Per rule: the condition facts of a run where it fires, and of one where it does not.
CASES: dict[str, tuple[dict[str, float], dict[str, float]]] = {
    "KF01": ({"thin_lines": 4}, {"thin_lines": 0}),
    "KF02": ({"blocking_findings": 1}, {"blocking_findings": 0}),
    "KF03": ({"selected_ultimate": 1000.0}, {"selected_ultimate": 0.0}),
    "KF04": ({"loss_ratio_change": 0.08}, {"loss_ratio_change": 0.04}),
    "KF05": ({"loss_ratio_change": -0.08}, {"loss_ratio_change": -0.04}),
    "KF06": ({"premium_change": 0.25}, {"premium_change": 0.05}),
    "KF07": ({"premium_change": -0.25}, {"premium_change": -0.05}),
    "KF08": ({"negative_paid_origins": 2}, {"negative_paid_origins": 0}),
    "KF09": ({"late_development_count": 1}, {"late_development_count": 0}),
    "KF10": ({"anomaly_lines_above": 1}, {"anomaly_lines_above": 0}),
    "KF11": ({"zero_denominator_cells": 1}, {"zero_denominator_cells": 0}),
    "KF12": ({"few_link_ratio_factors": 3}, {"few_link_ratio_factors": 0}),
    "KF13": ({"mack_not_run": 2}, {"mack_not_run": 0}),
    "KF14": ({"warning_findings": 2}, {"warning_findings": 0}),
    "KF15": ({"modules_skipped": 1}, {"modules_skipped": 0}),
    "KF16": ({"modules_limited": 1}, {"modules_limited": 0}),
    "KF20": ({"thin_evidence": 1}, {"thin_evidence": 0}),
    "KF21": ({"method_spread": 0.15}, {"method_spread": 0.05}),
    "KF22": ({"negative_paid_origins": 1}, {"negative_paid_origins": 0}),
    "KF23": ({"late_development_count": 1}, {"late_development_count": 0}),
    "KF24": ({"zero_denominator_cells": 2}, {"zero_denominator_cells": 0}),
    "KF25": ({"few_link_ratio_factors": 4}, {"few_link_ratio_factors": 0}),
    "KF26": (
        {"anomaly_rate": 0.2, "anomaly_rate_limit": 0.05},
        {"anomaly_rate": 0.01, "anomaly_rate_limit": 0.05},
    ),
    # RP01 1.2.0 (record 0345)
    "KF27": ({"munich_gap_size": 0.12}, {"munich_gap_size": 0.04}),
    "KF28": (
        {
            "back_test_bias_size": 0.08,
            "back_test_sign_share": 0.9,
            "back_test_sign_share_limit": 0.75,
        },
        {
            "back_test_bias_size": 0.01,
            "back_test_sign_share": 0.9,
            "back_test_sign_share_limit": 0.75,
        },
    ),
    "KF29": ({"tail_fitted_change": 0.23}, {"tail_fitted_change": 0.0}),
    "KF30": ({"tail_up_change": 0.4}, {"tail_up_change": 0.1}),
    "KF31": ({"gpd_shape": 0.68}, {"gpd_shape": 0.35}),
    "KF32": (
        {"cohort_logrank_p": 0.001, "cohort_significance": 0.01}
        | {"cohort_median_ratio": 1.6, "cohort_median_ratio_limit": 1.25},
        {"cohort_logrank_p": 0.47, "cohort_significance": 0.01}
        | {"cohort_median_ratio": 1.6, "cohort_median_ratio_limit": 1.25},
    ),
    "KF33": ({"range_upper_width": 0.46}, {"range_upper_width": 0.1}),
    "KF34": ({"discount_share": 0.44}, {"discount_share": 0.0}),
    "KF35": ({"recovered_to_date": 75.0}, {"recovered_to_date": 0.0}),
    "KF36": ({"recovery_differences": 2}, {"recovery_differences": 0}),
    "KF37": (
        {"recovery_ratio_drop": 0.6, "recovery_drop_limit": 0.5},
        {"recovery_ratio_drop": 0.4, "recovery_drop_limit": 0.5},
    ),
    "KF38": (
        {"expense_ratio_change_size": 0.03, "expense_ratio_change_limit": 0.02},
        {"expense_ratio_change_size": 0.01, "expense_ratio_change_limit": 0.02},
    ),
    "KF39": (
        {"commission_ratio_change_size": 0.03, "expense_ratio_change_limit": 0.02},
        {"commission_ratio_change_size": 0.01, "expense_ratio_change_limit": 0.02},
    ),
    "KF40": (
        {"unallocated_expense_share": 0.4, "unallocated_expense_share_limit": 0.25},
        {"unallocated_expense_share": 0.1, "unallocated_expense_share_limit": 0.25},
    ),
    "KF41": ({"unit_cost_periods_missing": 1}, {"unit_cost_periods_missing": 0}),
    "KF42": (
        {"thin_unpaid_change_size": 0.08, "thin_factor_change_limit": 0.02},
        {"thin_unpaid_change_size": 0.01, "thin_factor_change_limit": 0.02},
    ),
    "KF43": (
        {"tail_default": 1, "tail_default_concern": 1},
        {"tail_default": 1, "tail_default_concern": 0},
    ),
    # RP01 1.5.0 (F2a, record 0408): the facts come from the run of M08
    "KF44": ({"reinsurance_differences": 1}, {"reinsurance_differences": 0}),
    "KF45": ({"layers_exhausted": 1}, {"layers_exhausted": 0}),
    "KF46": (
        {"approximate_allocation_share": 0.06, "approximate_allocation_share_limit": 0.05},
        {"approximate_allocation_share": 0.05, "approximate_allocation_share_limit": 0.05},
    ),
}
# RP01 1.3.0 (record 0388): their facts come from the tables of M07 and M09, which
# tests/report/test_pages_m07_m09.py builds
NEW_IN_1_3 = {f"KF{n}" for n in range(35, 42)}
NEW_IN_1_2 = {f"KF{n}" for n in range(27, 35)}
# RP01 1.5.0 (record 0408): their facts come from the run of M08, which the tiny baseline skips
NEW_IN_1_5 = {"KF44", "KF45", "KF46"}


def _facts(rule: FindingRule, values: dict[str, float]) -> dict[str, Fact]:
    """The template's facts with plain fillers, and the case's condition facts."""
    facts = {name: Fact("filled", "text") for name in facts_named(rule)}
    facts.update({name: Fact(value, "ratio") for name, value in values.items()})
    return facts


def test_every_rule_has_a_firing_and_a_quiet_case() -> None:
    assert set(CASES) == set(RULES)


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_rule_fires_on_its_condition(rule_id: str) -> None:
    rule = RULES[rule_id]
    facts = _facts(rule, CASES[rule_id][0])
    assert holds(rule, facts)
    found = evaluate([rule], {rule.scope: [("key", "line-0", facts)]})
    assert [f.rule for f in found] == [rule_id]
    assert "{" not in found[0].text and found[0].text == sentence(rule, facts)


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_rule_stays_quiet_otherwise(rule_id: str) -> None:
    rule = RULES[rule_id]
    facts = _facts(rule, CASES[rule_id][1])
    assert not holds(rule, facts)
    assert evaluate([rule], {rule.scope: [("key", "line-0", facts)]}) == []


def test_a_rule_whose_fact_is_unknown_does_not_fire() -> None:
    rule = RULES["KF06"]
    facts = _facts(rule, {})
    facts.pop("premium_change")
    assert not holds(rule, facts)


def test_unreadable_conditions_and_unknown_template_facts_are_errors() -> None:
    with pytest.raises(RuleError):
        parse_condition("thin_lines is large")
    rule = RULES["KF01"]
    with pytest.raises(RuleError):
        sentence(rule, {"thin_lines": Fact(1, "count")})


def test_facts_are_shown_by_kind_with_cv06_rounding() -> None:
    assert Fact(1234.5, "amount").show() == "1,235"
    assert Fact(0.1234, "ratio").show() == "12.3%"
    assert Fact(1.38184, "factor").show() == "1.382"
    assert Fact(99.94, "score").show() == "99.9"
    assert Fact(4, "count").show() == "4"


def test_conditions_compare_facts_with_facts() -> None:
    rule = RULES["KF26"]
    assert {c.other for c in parse_condition(rule.condition)} == {"anomaly_rate_limit"}


@pytest.mark.integration
def test_every_fact_a_rule_names_is_computed_for_its_scope(default_run: RunResult) -> None:
    """On the tiny baseline every named fact exists in at least one fact set of the scope
    (facts that cannot be known, such as a flag rate of an unscored line, may be absent)."""
    r = default_run
    scoped, _ = scoped_facts(r.reserving, r.analysis, r.quality, anomaly_rates(r.anomalies))
    known = {scope: set().union(*(set(f) for _, _, f in sets)) for scope, sets in scoped.items()}
    missing = {
        (rule.id, name)
        for rule in RULES.values()
        if rule.id
        not in NEW_IN_1_2
        | NEW_IN_1_3
        | NEW_IN_1_5
        | {"KF42"}  # need methods or tables the call lacks
        for name in facts_named(rule)
        if name not in known[rule.scope]
    }
    assert missing == set()


@pytest.mark.integration
def test_the_tiny_baseline_says_its_evidence_is_thin(default_run: RunResult) -> None:
    model = default_run.report_data
    first = model["key_findings"][0]
    assert first["rule"] == "KF01" and first["banner"]
    assert first["text"].startswith("Only 4 origin periods (2022 to 2025)")
    assert "not how precise it is" in first["text"]
    assert model["banners"] == [first["text"]]
    assert len(model["key_findings"]) <= 8
    # every module ran except M08, which needs reinsurance treaties (F2a, record 0407)
    not_run = [f for f in model["key_findings"] + model["further_findings"] if f["rule"] == "KF15"]
    assert len(not_run) == 1 and "(M08 Reinsurance)" in not_run[0]["text"]


# RP01 1.2.1 (record 0347): the part of the condition that the sentence needs

SIGN_LIMIT = {"back_test_sign_share_limit": 0.75}
RATIO_LIMIT = {"cohort_median_ratio_limit": 1.25}


def _fires(rule_id: str, values: dict[str, float]) -> bool:
    return holds(RULES[rule_id], _facts(RULES[rule_id], values))


def test_the_rule_file_names_its_settings() -> None:
    assert load_specs().finding_rules.settings == SIGN_LIMIT | RATIO_LIMIT | {
        "recovery_drop_limit": 0.5,
        "expense_ratio_change_limit": 0.02,
        "unallocated_expense_share_limit": 0.25,
        "thin_factor_change_limit": 0.02,
        "approximate_allocation_share_limit": 0.05,  # RP01 1.5.0, record 0408
    }


def test_kf28_needs_one_sign_in_the_errors_of_the_back_test() -> None:
    big = {"back_test_bias_size": 0.08} | SIGN_LIMIT
    assert _fires("KF28", big | {"back_test_sign_share": 0.75})
    assert not _fires("KF28", big | {"back_test_sign_share": 0.6})
    assert not _fires("KF28", big)  # a run without the share does not say "one direction"


def test_kf31_has_the_fixed_shape_and_no_other_limit_can_be_given() -> None:
    rule = RULES["KF31"]
    assert [(c.fact, c.op, c.other) for c in parse_condition(rule.condition)] == [
        ("gpd_shape", ">=", "0.5")
    ]
    assert "gpd_shape_limit" not in facts_named(rule)
    assert "0.5" in rule.template and "0,5" in rule.template_tr
    assert "gpd_shape_limit" not in load_specs().finding_rules.settings
    # a limit given as a fact changes nothing: the rule does not read it
    assert not _fires("KF31", {"gpd_shape": 0.49, "gpd_shape_limit": 0.3})
    assert _fires("KF31", {"gpd_shape": 0.5, "gpd_shape_limit": 0.9})


def test_kf32_needs_an_effect_besides_the_test() -> None:
    significant = {"cohort_logrank_p": 0.001, "cohort_significance": 0.01} | RATIO_LIMIT
    assert _fires("KF32", significant | {"cohort_median_ratio": 1.25})
    assert not _fires("KF32", significant | {"cohort_median_ratio": 1.1})
    assert not _fires("KF32", significant)  # fewer than two report years with 20 closings


def _back_test(errors: list[float], bias: float) -> dict[str, pl.DataFrame]:
    summary = {"kind": "summary", "method": "MT10", "horizon_months": 12, "origins": len(errors)}
    rows = [{"kind": "error", "method": "MT10", "horizon_months": 12, "error": e} for e in errors]
    rows += [{"kind": "error", "method": "MT10", "horizon_months": 24, "error": -1.0}]
    rows += [summary | {"bias": bias}]
    frame = pl.DataFrame(
        [{"segment": "S", "line": "L", "bias": None, "origins": None} | r for r in rows]
    )
    return {"back_test.csv": frame}


def test_the_sign_share_counts_the_origins_with_the_sign_of_the_mean() -> None:
    facts: dict[str, Fact] = {}
    add_back_test_facts(facts, _back_test([0.1, 0.2, 0.3, -0.05], 0.1), "S", "L")
    assert facts["back_test_sign_share"].value == 0.75
    assert facts["back_test_bias_size"].value == 0.1
    negative: dict[str, Fact] = {}
    add_back_test_facts(negative, _back_test([0.1, -0.2, -0.3, 0.0], -0.1), "S", "L")
    assert negative["back_test_sign_share"].value == 0.5  # a zero error has no sign


def _cohorts(events: dict[str, int], medians: dict[str, float | None]) -> dict[str, pl.DataFrame]:
    cohorts = [{"segment": "S", "report_year": y, "events": n, "logrank_p": 0.001}
               for y, n in events.items()]  # fmt: skip
    percentiles = [
        {"segment": "S", "grouping": "report_year", "group": y, "percentile": 0.5, "time": t}
        for y, t in medians.items()
    ]
    return {
        "survival_cohorts.csv": pl.DataFrame(cohorts),
        "survival_time_percentiles.csv": pl.DataFrame(percentiles),
    }


def test_the_median_ratio_uses_the_report_years_with_twenty_events() -> None:
    tables = _cohorts(
        {"2021": 40, "2022": 25, "2023": 19, "2024": 30},
        {"2021": 100.0, "2022": 150.0, "2023": 900.0, "2024": None},
    )
    facts: dict[str, Fact] = {}
    add_segment_facts(facts, tables, "S")
    assert facts["cohort_median_ratio"].value == 1.5  # 2023 has 19 events, 2024 no median
    alone: dict[str, Fact] = {}
    add_segment_facts(
        alone,
        _cohorts({"2021": 40, "2022": 5}, {"2021": 1.0, "2022": 9.0}),
        "S",
    )
    assert "cohort_median_ratio" not in alone
