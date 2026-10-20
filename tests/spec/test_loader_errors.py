"""The loader rejects invalid files, repeated IDs and broken references, naming each problem."""

import shutil
from pathlib import Path

import pytest

from actuarycanary.spec.catalogue import SpecCatalogue, SpecFile
from actuarycanary.spec.loader import (
    SpecError,
    duplicate_id_problems,
    find_spec_root,
    load_specs,
    read_spec_files,
)
from actuarycanary.spec.models import SpecBase
from actuarycanary.spec.references import reference_problems

PR04_FILE = "PR04-cancellation-rate.yaml"


@pytest.fixture(scope="module")
def catalogue() -> SpecCatalogue:
    return load_specs()


@pytest.fixture
def measures_root(tmp_path: Path) -> Path:
    """A spec root holding only PR04, enough for file-level checks."""
    (tmp_path / "measures").mkdir()
    shutil.copy(find_spec_root() / "measures" / PR04_FILE, tmp_path / "measures" / PR04_FILE)
    return tmp_path


def _file_problems(root: Path) -> str:
    files, problems = read_spec_files(root)
    return "\n".join([*problems, *duplicate_id_problems(files)])


def _replace(catalogue: SpecCatalogue, spec: SpecBase) -> SpecCatalogue:
    files = (SpecFile(f.kind, f.path, spec) if f.spec.id == spec.id else f for f in catalogue.files)
    return SpecCatalogue(tuple(files))


def _reference_problems(catalogue: SpecCatalogue, spec: SpecBase) -> str:
    return "\n".join(reference_problems(_replace(catalogue, spec)))


def test_load_specs_raises_spec_error_listing_problems(tmp_path: Path) -> None:
    with pytest.raises(SpecError) as error:
        load_specs(tmp_path)
    assert any("columns.yaml: missing" in p for p in error.value.problems)


def test_missing_required_key_is_reported_with_its_file(measures_root: Path) -> None:
    path = measures_root / "measures" / PR04_FILE
    path.write_text(path.read_text(encoding="utf-8").replace("title_tr:", "# "), encoding="utf-8")
    problems = _file_problems(measures_root)
    assert PR04_FILE in problems and "title_tr" in problems


def test_unknown_key_is_rejected(measures_root: Path) -> None:
    path = measures_root / "measures" / PR04_FILE
    path.write_text(path.read_text(encoding="utf-8") + "colour: blue\n", encoding="utf-8")
    assert "colour" in _file_problems(measures_root)


def test_repeated_id_is_rejected(measures_root: Path) -> None:
    shutil.copy(measures_root / "measures" / PR04_FILE, measures_root / "measures" / "PR04-b.yaml")
    assert "spec id PR04 is used 2 times" in _file_problems(measures_root)


def test_file_must_be_named_after_its_id(measures_root: Path) -> None:
    (measures_root / "measures" / PR04_FILE).rename(measures_root / "measures" / "PR99.yaml")
    assert "must start with the spec id PR04" in _file_problems(measures_root)


def test_measure_with_undefined_field_is_rejected(catalogue: SpecCatalogue) -> None:
    pr04 = catalogue.measures["PR04"]
    broken = pr04.model_copy(update={"requires": [*pr04.requires, "premiums.booking_day"]})
    assert "PR04: field premiums.booking_day is not defined" in _reference_problems(
        catalogue, broken
    )


def test_method_using_undefined_spec_is_rejected(catalogue: SpecCatalogue) -> None:
    broken = catalogue.methods["MT05"].model_copy(update={"uses": ["MT04", "PR99"]})
    assert "MT05: uses PR99" in _reference_problems(catalogue, broken)


def test_module_with_undefined_measure_is_rejected(catalogue: SpecCatalogue) -> None:
    broken = catalogue.modules["M06"].model_copy(update={"measures": ["CL12", "CL99"]})
    assert "M06: measure CL99 is not defined" in _reference_problems(catalogue, broken)


def test_module_must_list_methods_its_measures_use(catalogue: SpecCatalogue) -> None:
    broken = catalogue.modules["M05"].model_copy(update={"methods": ["MT10"]})
    assert "M05: needs method MT02" in _reference_problems(catalogue, broken)


def test_module_must_list_concepts_its_measures_require(catalogue: SpecCatalogue) -> None:
    broken = catalogue.modules["M05"].model_copy(update={"optional": ["market"]})
    assert "M05: its measures or methods require concept expenses" in _reference_problems(
        catalogue, broken
    )


def test_conflicting_column_alias_is_rejected(catalogue: SpecCatalogue) -> None:
    aliases = catalogue.column_aliases
    columns = [
        e.model_copy(update={"aliases": [*e.aliases, "ÖDENEN"]}) if e.field == "case_reserve" else e
        for e in aliases.columns
    ]
    broken = aliases.model_copy(update={"columns": columns})
    assert "token 'odenen' maps to ['case_reserve', 'paid_to_date']" in _reference_problems(
        catalogue, broken
    )


def test_field_without_alias_entry_is_rejected(catalogue: SpecCatalogue) -> None:
    aliases = catalogue.column_aliases
    columns = [
        e.model_copy(update={"concepts": ["claims"]}) if e.field == "product" else e
        for e in aliases.columns
    ]
    broken = aliases.model_copy(update={"columns": columns})
    assert "policies.product has 0 alias entries" in _reference_problems(catalogue, broken)


def test_value_alias_classes_must_match_the_field(catalogue: SpecCatalogue) -> None:
    aliases = catalogue.value_aliases
    values = [
        e.model_copy(update={"classes": {**e.classes, "DISPUTED": ["IHTILAF"]}})
        if e.field == "status"
        else e
        for e in aliases.values
    ]
    broken = aliases.model_copy(update={"values": values})
    assert "classes of claim_valuations.status differ" in _reference_problems(catalogue, broken)
