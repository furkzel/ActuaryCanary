"""The specification files in spec/ are valid, unique and consistent with each other."""

import pytest

from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.spec.loader import duplicate_id_problems, index_rows, load_specs
from actuarycanary.spec.references import field_exists, reference_problems

# The version 1.0 subset of blueprint section 8.1, fixed by work item P01.
MEASURES_V1 = {
    *(f"PR0{n}" for n in range(1, 7)),
    *(f"CL{n:02d}" for n in range(1, 13)),
    "RC01", "RC02", "RI01", "RI02", "EX01", "EX02", "EX03",
    "RT01", "RT02", "RS01", "RS02", "RS03", "AE01", "DQ01",
}  # fmt: skip
CONCEPTS_V1 = {"claim_valuations", "claims", "policies", "premiums", "expenses", "market"}
MODULES_V1 = {f"M0{n}" for n in range(1, 7)}
# Planned for phase 2 by work item P20 (decision 0200): drafts, left out of every run.
CONCEPTS_PLANNED = {
    "reinsurance_treaties", "reinsurance_transactions", "recoveries", "ledger",
    "interest_rates", "life_in_force", "life_events", "fund_flows",
}  # fmt: skip
MODULES_PLANNED = {f"M{n:02d}" for n in range(7, 14)}
# Built by the integration P25b (record 0620): the tier B reserving methods, the severity
# methods, and the measure AE02, the back-test error. P25c built MT19 (survival).
METHODS_BUILT_P25B = {f"MT{n}" for n in (*range(11, 19), 22)}
METHODS_BUILT_P25C = {"MT19"}
MEASURES_BUILT_P25B = {"AE02"}
METHODS_PLANNED = {f"MT{n}" for n in range(11, 30)} - METHODS_BUILT_P25B - METHODS_BUILT_P25C


@pytest.fixture(scope="module")
def catalogue() -> SpecCatalogue:
    return load_specs()


@pytest.fixture(scope="module")
def planned() -> SpecCatalogue:
    """Every spec, the planned ones included (decision 0200)."""
    return load_specs(planned=True)


def test_all_specs_load_and_validate(catalogue: SpecCatalogue) -> None:
    assert len(catalogue.files) == len(catalogue.ids)


def test_spec_ids_are_unique(catalogue: SpecCatalogue) -> None:
    assert duplicate_id_problems(list(catalogue.files)) == []


def test_version_1_scope_is_complete(catalogue: SpecCatalogue) -> None:
    assert set(catalogue.data) == CONCEPTS_V1
    assert set(catalogue.measures) == MEASURES_V1 | MEASURES_BUILT_P25B
    assert {m for m in catalogue.methods if int(m[2:]) >= 11} == (
        METHODS_BUILT_P25B | METHODS_BUILT_P25C
    )
    assert set(catalogue.modules) == MODULES_V1
    assert {f"CV0{n}" for n in range(1, 7)} <= set(catalogue.conventions)


def test_every_reference_resolves(catalogue: SpecCatalogue) -> None:
    assert reference_problems(catalogue) == []


def test_measures_and_methods_reference_only_defined_fields(catalogue: SpecCatalogue) -> None:
    specs = [*catalogue.measures.values(), *catalogue.methods.values()]
    undefined = [
        (spec.id, ref)
        for spec in specs
        for ref in [*spec.requires, *spec.optional]
        if not field_exists(catalogue, ref)
    ]
    assert undefined == []


def test_modules_reference_only_defined_measures_and_methods(catalogue: SpecCatalogue) -> None:
    for module in catalogue.modules.values():
        assert set(module.measures) <= set(catalogue.measures), module.id
        assert set(module.methods) <= set(catalogue.methods), module.id


def test_every_measure_names_its_own_test_file(catalogue: SpecCatalogue) -> None:
    for measure in catalogue.measures.values():
        assert measure.test.path.startswith(f"tests/measures/test_{measure.id.lower()}_")


def test_index_lists_every_spec_id(planned: SpecCatalogue) -> None:
    rows = index_rows(planned)
    assert {row[1] for row in rows} == planned.ids
    assert all(row[3] in {"draft", "reviewed"} for row in rows)
    assert {row[1] for row in rows if row[4] == "planned"} == planned.ids - planned.built().ids


def test_run_catalogue_holds_only_built_specs(
    catalogue: SpecCatalogue, planned: SpecCatalogue
) -> None:
    assert all(f.spec.implemented for f in catalogue.files)
    assert catalogue.ids == planned.built().ids
    assert catalogue.ids < planned.ids


def test_planned_specs_are_drafts(planned: SpecCatalogue) -> None:
    assert all(
        f.spec.status in ("draft", "reviewed") for f in planned.files if not f.spec.implemented
    )


def test_every_reference_of_the_planned_specs_resolves(planned: SpecCatalogue) -> None:
    assert reference_problems(planned) == []


def test_phase_2_scope_is_planned(planned: SpecCatalogue) -> None:
    not_built = {f.spec.id for f in planned.files if not f.spec.implemented}
    assert not_built >= CONCEPTS_PLANNED | MODULES_PLANNED | METHODS_PLANNED
    assert {"CV09", "CV10", "CV11", "CV12", "AL03", "AL04"} <= not_built
    assert not (METHODS_BUILT_P25B | METHODS_BUILT_P25C | MEASURES_BUILT_P25B) & not_built
    assert {m for m in METHODS_PLANNED if planned.methods[m].tier == "C"} == {
        f"MT{n}" for n in range(23, 30)
    }
