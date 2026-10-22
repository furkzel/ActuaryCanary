"""The module runner: modules run when their concepts are present, and say why they did not
when a concept is missing or a BLOCKING finding hits a field they need (decisions 0014, 0032,
0051)."""

import json
from datetime import date

import pytest

from actuarycanary.canonical.feeds import Finding
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.modules.output import analysis_json
from actuarycanary.modules.runner import ModuleState, run_modules
from actuarycanary.structures.periods import Period
from tests.measures.helpers import CATALOGUE, make_inputs
from tests.quality.builders import claim, cv, expense, policy, premium
from tests.quality.test_engine import report

CLAIMS_ONLY = {"claim_valuations": [cv(1), cv(2, paid_to_date=5.0)]}
FULL = {
    **CLAIMS_ONLY,
    "claims": [claim()],
    "policies": [policy(end_date=date(2025, 1, 1))],
    "premiums": [premium()],
    "expenses": [expense(type="ACQUISITION")],
}


def run(rows: dict, findings: dict | None = None):
    return run_modules(
        CATALOGUE,
        make_inputs(rows),
        report(rows, findings),
        Period.YEAR,
        ReinsuranceBasis.GROSS,
        ValueBasis.NOMINAL,
    )


@pytest.fixture(scope="module")
def full():
    """One run of every module on every concept, shared by the tests that only read it."""
    return run(FULL)


def states(analysis) -> dict[str, ModuleState]:
    return {m.module: m.state for m in analysis.modules}


def test_modules_run_when_their_concepts_are_present(full) -> None:
    analysis = full
    assert [m.module for m in analysis.modules] == ["M01", "M02", "M03", "M04", "M05", "M06"]
    found = states(analysis)
    assert all(state is not ModuleState.SKIPPED for state in found.values()), found
    assert found["M01"] is ModuleState.RAN
    assert analysis.get("M03").available  # claims measures were computed
    assert analysis.get("M02").available  # premium measures were computed
    # a limited module says what is missing: the methods that are not built yet
    assert "methods not built yet" in " ".join(analysis.get("M04").reasons)


def test_modules_without_their_concepts_are_skipped_with_the_reason_of_their_spec() -> None:
    analysis = run(CLAIMS_ONLY)
    found = states(analysis)
    assert found["M02"] is ModuleState.SKIPPED and found["M05"] is ModuleState.SKIPPED
    assert found["M01"] is ModuleState.RAN
    assert found["M03"] is not ModuleState.SKIPPED and found["M06"] is not ModuleState.SKIPPED
    assert analysis.get("M02").reasons == (CATALOGUE.modules["M02"].skip_reason,)
    assert "no premium file was loaded" in analysis.get("M02").reasons[0]
    assert analysis.get("M02").measures == ()  # nothing was attempted


def test_a_blocking_finding_on_a_required_field_skips_the_modules_that_need_it() -> None:
    keyless = Finding("claim_valuations", "DV-CLV-01", "BLOCKING", 1, "rows without claim_id", (3,))
    analysis = run(FULL, {"claim_valuations": (keyless,)})
    found = states(analysis)
    for module in ("M03", "M04", "M06"):
        assert found[module] is ModuleState.SKIPPED, module
        assert "DV-CLV-01" in analysis.get(module).reasons[0]
    assert found["M01"] is ModuleState.RAN  # the quality report is never blocked


def test_a_blocking_finding_on_an_optional_concept_removes_only_the_measures_that_use_it() -> None:
    bad = Finding("claims", "DV-CLM-01", "BLOCKING", 2, "rows without claim_id", (2,))
    analysis = run(FULL, {"claims": (bad,)})
    m02 = analysis.get("M02")
    assert m02.state is ModuleState.LIMITED
    blocked = [r for r in m02.measures if r.reason.startswith("blocked by a data finding")]
    assert [r.measure for r in blocked] == ["RI01"]  # RI01 reads claims fields
    assert all(not r.available for r in blocked)
    assert any(r.available and r.measure == "PR01" for r in m02.measures)  # PR01 does not
    # every claims measure reads some claims field for its optional breakdowns: all are blocked
    assert not analysis.get("M03").available


def test_warning_findings_never_stop_a_module() -> None:
    warning = Finding("claim_valuations", "DV-CLV-03", "WARNING", 1, "empty currency", (3,))
    found = states(run(FULL, {"claim_valuations": (warning,)}))
    assert ModuleState.SKIPPED not in found.values()
    assert found["M01"] is ModuleState.RAN and found["M03"] is ModuleState.LIMITED


def test_results_list_each_measure_view_once_and_the_json_names_every_module(full) -> None:
    analysis = full
    keys = [(r.measure, r.request) for r in analysis.results()]
    assert len(keys) == len(set(keys))
    data = json.loads(analysis_json(analysis))
    assert [m["module"] for m in data["modules"]] == ["M01", "M02", "M03", "M04", "M05", "M06"]
    m02 = data["modules"][1]
    assert m02["state"] in ("ran", "limited") and m02["measures"]
    assert {"measure", "spec_version", "available", "rows", "reason"} <= set(m02["measures"][0])


def test_a_measure_defined_on_one_basis_only_is_shown_on_it_with_a_note() -> None:
    analysis = run_modules(
        CATALOGUE,
        make_inputs(FULL),
        report(FULL),
        Period.YEAR,
        ReinsuranceBasis.GROSS,
        ValueBasis.INFLATION_ADJUSTED,
    )
    notes = [n for r in analysis.get("M03").measures for n in r.notes]
    assert any("defined on GROSS, NOMINAL only" in n for n in notes)
