"""The quality report finds every fault the synthetic generator injected (truth/)."""

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from actuarycanary.pipeline import RunResult, run
from actuarycanary.quality.model import QualityReport

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"
CACHE = Path(".cache")
# injected fault type -> (concept, rule that must report it)
RULE_OF_FAULT = {
    "duplicate_valuation_rows": ("claim_valuations", "DV-CLV-06"),
    "paid_to_date_decreasing_without_recovery": ("claim_valuations", "DV-CLV-07"),
    "extreme_payment_outliers": ("claim_valuations", "DV-CLV-15"),
    "missing_currency": ("claim_valuations", "DV-CLV-03"),
    "unknown_status_labels": ("claim_valuations", "DV-CLV-04"),
    "report_before_occurrence": ("claims", "DV-CLM-04"),
    "duplicate_premium_rows": ("premiums", "DV-PRM-02"),
}
pytestmark = pytest.mark.integration


def _faults(scenario: str) -> dict[str, list[dict[str, str]]]:
    with (FIXTURES / scenario / "truth" / "injected_faults.csv").open(encoding="utf-8") as f:
        by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in csv.DictReader(f):
            by_type[row["fault_type"]].append(row)
    return by_type


def _quality(scenario: str, out: Path) -> QualityReport:
    result: RunResult = run(FIXTURES / scenario, out, cache_dir=CACHE)
    return result.quality


@pytest.fixture(scope="module")
def messy(tmp_path_factory: pytest.TempPathFactory) -> QualityReport:
    return _quality("messy_headers", tmp_path_factory.mktemp("messy"))


@pytest.fixture
def baseline(default_run: RunResult) -> QualityReport:
    return default_run.quality


def _found(report: QualityReport, concept: str, rule: str) -> tuple[int, set[tuple[str, int]]]:
    hits = [f for f in report.findings if (f.concept, f.rule) == (concept, rule)]
    return sum(f.count for f in hits), {(r.file, r.row) for f in hits for r in f.refs}


@pytest.mark.slow
def test_messy_headers_tiny_every_injected_fault_is_found(messy: QualityReport) -> None:
    faults = _faults("messy_headers")
    assert set(faults) == set(RULE_OF_FAULT)
    for fault, rows in faults.items():
        concept, rule = RULE_OF_FAULT[fault]
        count, refs = _found(messy, concept, rule)
        assert count == len(rows), fault
        injected = {(r["file"], int(r["sheet_row"])) for r in rows}
        assert refs <= injected, fault  # listed examples are among the injected rows
        if len(rows) <= 5:
            assert refs == injected, fault


def test_baseline_tiny_has_only_the_injected_faults(baseline: QualityReport) -> None:
    faults = _faults("baseline")
    expected = {RULE_OF_FAULT[f] for f in faults}
    warned = {(f.concept, f.rule) for f in baseline.findings if f.severity != "INFO"}
    assert warned == expected  # no WARNING or BLOCKING finding without an injected fault
    assert baseline.count("BLOCKING") == 0
    for fault, rows in faults.items():
        concept, rule = RULE_OF_FAULT[fault]
        assert _found(baseline, concept, rule)[0] == len(rows), fault


def test_injected_faults_lower_the_score_only_a_little(baseline: QualityReport) -> None:
    assert baseline.overall.value is not None and 98 < baseline.overall.value < 100
    assert baseline.modules and all(
        m.status != "unable" for m in baseline.modules if m.module in ("M03", "M04")
    )
