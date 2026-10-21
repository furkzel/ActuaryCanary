"""Scores, findings, module status and coverage of a quality report, on tiny feeds."""

import json
from datetime import date

import pytest
from rich.console import Console

from actuarycanary.canonical.feeds import CanonicalFeed, Finding
from actuarycanary.quality.engine import evaluate
from actuarycanary.quality.model import QualityReport
from actuarycanary.quality.output import print_summary, quality_json
from actuarycanary.spec.loader import load_specs
from tests.quality.builders import claim, cv, frames

CATALOGUE = load_specs()


def feeds(rows: dict, findings: dict[str, tuple[Finding, ...]] | None = None):
    built = frames(rows)
    out = {
        c: CanonicalFeed(
            c,
            "1",
            f,
            tuple(x for x in f.columns if not x.startswith("_")),
            (findings or {}).get(c, ()),
        )
        for c, f in built.items()
    }
    return out, built


def report(rows: dict, findings: dict | None = None, **kwargs) -> QualityReport:
    loaded, raw = feeds(rows, findings)
    return evaluate(CATALOGUE, loaded, raw, **kwargs)


CLEAN = {"claim_valuations": [cv(1), cv(2, paid_to_date=5.0), cv(3, paid_to_date=5.0)]}
KEYLESS = Finding(
    "claim_valuations", "DV-CLV-01", "BLOCKING", 1, "rows without claim_id excluded", (3,)
)


def status(r: QualityReport) -> dict[str, str]:
    return {m.module: m.status for m in r.modules}


def test_clean_feed_scores_one_hundred_and_has_no_finding() -> None:
    r = report(CLEAN)
    assert r.overall.value == 100.0 and r.findings == ()
    assert r.by_concept["claim_valuations"].value == 100.0
    assert r.by_field["claim_valuations.paid_to_date"].value == 100.0
    assert r.cut_off == date(2024, 3, 31)


def test_one_failing_rule_lowers_concept_field_and_dimension_scores() -> None:
    rows = {
        "claim_valuations": [
            cv(1, paid_to_date=9.0),
            cv(2, paid_to_date=5.0),
            cv(3, paid_to_date=5.0),
        ]
    }
    r = report(rows)
    assert [f.rule for f in r.findings] == ["DV-CLV-07"]
    assert r.findings[0].count == 1 and r.findings[0].checked == 2
    assert r.by_field["claim_valuations.paid_to_date"].value < 100  # type: ignore[operator]
    assert r.by_field["claim_valuations.currency"].value == 100.0
    assert r.by_dimension["consistency"].value < 100  # type: ignore[operator]
    assert r.by_dimension["validity"].value == 100.0


def test_overall_score_is_over_all_rules_not_an_average_of_concepts() -> None:
    rows = {**CLEAN, "claims": [claim(report_date=date(2023, 12, 1))]}
    r = report(rows)
    concept_mean = sum(s.value for s in r.by_concept.values()) / len(r.by_concept)  # type: ignore[misc]
    rules = [s for s in r.rules if s.severity != "INFO"]
    expected = (
        100 * sum(s.weight * s.passed / s.checked for s in rules) / sum(s.weight for s in rules)
    )
    assert r.overall.value == pytest.approx(expected)
    assert r.overall.value != pytest.approx(concept_mean)


def test_blocking_finding_stops_only_the_dependent_modules() -> None:
    r = report(CLEAN, {"claim_valuations": (KEYLESS,)})
    assert r.findings[0].severity == "BLOCKING" and r.findings[0].count == 1
    states = status(r)
    assert states["M04"] == "unable" and states["M03"] == "unable" and states["M06"] == "unable"
    assert states["M01"] == "ok"
    assert states["M02"] == "unable"  # premiums not loaded: its own reason, not this finding
    m04 = next(m for m in r.modules if m.module == "M04")
    assert "DV-CLV-01" in m04.reasons[0] and "claim_id" in "".join(r.findings[0].fields)


def test_blocking_finding_on_an_optional_concept_only_removes_what_needs_it() -> None:
    bad = Finding("claims", "DV-CLM-01", "BLOCKING", 2, "rows without claim_id excluded", (2,))
    r = report({**CLEAN, "claims": [claim()]}, {"claims": (bad,)})
    m04 = next(m for m in r.modules if m.module == "M04")
    assert m04.status == "limited" and m04.unavailable and "MT01" in m04.unavailable
    assert status(r)["M03"] == "limited"


def test_warning_finding_never_changes_module_status() -> None:
    warn = Finding("claim_valuations", "DV-CLV-03", "WARNING", 1, "empty currency", (3,))
    r = report(CLEAN, {"claim_valuations": (warn,)})
    assert status(r)["M04"] == "ok"
    assert r.findings[0].modules and "M04" in r.findings[0].modules


def test_findings_are_ordered_by_severity() -> None:
    warn = Finding("claim_valuations", "DV-CLV-03", "WARNING", 1, "empty currency", (3,))
    r = report(CLEAN, {"claim_valuations": (warn, KEYLESS)})
    assert [f.severity for f in r.findings] == ["BLOCKING", "WARNING"]


def test_coverage_lists_every_concept_and_what_was_not_loaded() -> None:
    r = report(
        CLEAN,
        sources={"claim_valuations": ("c.xlsx [s]",)},
        unreadable={"claims": "columns missing"},
    )
    by = {c.concept: c for c in r.coverage}
    assert len(by) == 6
    cv_cover = by["claim_valuations"]
    assert cv_cover.loaded and cv_cover.rows == 3
    assert (cv_cover.first, cv_cover.last) == (date(2024, 1, 31), date(2024, 3, 31))
    assert cv_cover.sources == ("c.xlsx [s]",)
    assert not by["premiums"].loaded and by["claims"].note == "columns missing"
    assert ("DV-PRM-01", "premiums is not loaded") in r.not_evaluated
    assert ("DV-CLM-04", "columns missing") in r.not_evaluated


def test_quality_json_is_deterministic_and_complete() -> None:
    r = report(CLEAN, {"claim_valuations": (KEYLESS,)})
    text = quality_json(r)
    assert text == quality_json(r)
    body = json.loads(text)
    assert set(body) >= {"scores", "findings", "modules", "coverage", "rules", "not_evaluated"}
    assert set(body["scores"]) == {"overall", "by_concept", "by_field", "by_dimension"}
    assert body["findings"][0]["refs"][0] == {"file": "f.xlsx", "sheet": "s", "row": 3}


def test_terminal_summary_shows_score_findings_and_blocked_modules() -> None:
    console = Console(record=True, width=200)
    print_summary(console, report(CLEAN, {"claim_valuations": (KEYLESS,)}))
    out = console.export_text()
    assert "Data quality" in out and "DV-CLV-01" in out and "M04" in out and "unable" in out
