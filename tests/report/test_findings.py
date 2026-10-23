"""The finding rules of RP01 (spec/report/findings.yaml): each fires on its condition and only
then, fills its template from facts, and names facts the run computes (decision 0070)."""

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
}


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
    assert "KF15" not in {f["rule"] for f in model["further_findings"]}  # every module ran
