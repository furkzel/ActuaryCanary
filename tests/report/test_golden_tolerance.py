"""The tolerance comparison of the golden test (decision 0627)."""

import copy

import pytest

from actuarycanary.pipeline import RunResult
from tests.report.golden_tolerance import (
    TOLERANCE_FILES,
    compare_tables,
    differences,
    split_tables,
    table_record,
)

BASE = table_record("group,family,shape,se\nMOTOR_OD,pareto2,1.2345678,0.5\nPROPERTY,gamma,2.0,\n")


def changed(text: str):
    return compare_tables(BASE, table_record(text))


def test_equal_tables_are_equal() -> None:
    result = compare_tables(BASE, copy.deepcopy(BASE))
    assert result.equal
    assert result.largest_relative == 0.0


def test_a_relative_change_of_1e_6_in_a_numeric_cell_passes() -> None:
    result = changed(
        "group,family,shape,se\nMOTOR_OD,pareto2,1.2345690345,0.5\nPROPERTY,gamma,2.0,\n"
    )
    assert result.equal
    assert 9e-7 < result.largest_relative < 1.1e-6


def test_a_relative_change_of_1e_3_in_a_numeric_cell_fails() -> None:
    result = changed("group,family,shape,se\nMOTOR_OD,pareto2,1.2358,0.5\nPROPERTY,gamma,2.0,\n")
    assert not result.equal
    assert "row 1, shape" in result.problems[0]


def test_a_changed_text_cell_fails() -> None:
    result = changed("group,family,shape,se\nMOTOR_OD,gamma,1.2345678,0.5\nPROPERTY,gamma,2.0,\n")
    assert not result.equal
    assert "family" in result.problems[0]


def test_a_text_cell_that_becomes_a_number_or_empty_fails() -> None:
    assert not changed(
        "group,family,shape,se\nMOTOR_OD,3,1.2345678,0.5\nPROPERTY,gamma,2.0,\n"
    ).equal
    assert not changed(
        "group,family,shape,se\nMOTOR_OD,pareto2,1.2345678,\nPROPERTY,gamma,2.0,\n"
    ).equal


@pytest.mark.parametrize(
    "header",
    [
        "group,family,shape",  # a column removed
        "group,family,shape,se,aic",  # a column added
        "group,family,se,shape",  # same set, other order
        "group,family,alpha,se",  # a column renamed
    ],
)
def test_a_changed_column_set_fails(header: str) -> None:
    result = compare_tables(BASE, table_record(f"{header}\nMOTOR_OD,pareto2,1.2345678,0.5\n"))
    assert not result.equal
    assert result.problems[0].startswith("columns")


def test_a_changed_number_of_rows_fails() -> None:
    assert not changed("group,family,shape,se\nMOTOR_OD,pareto2,1.2345678,0.5\n").equal


def test_the_absolute_tolerance_decides_near_zero() -> None:
    zero = table_record("a\n0.0\n")
    assert compare_tables(zero, table_record("a\n5e-13\n")).equal
    assert not compare_tables(zero, table_record("a\n5e-11\n")).equal


def test_not_a_number_and_infinity_must_match() -> None:
    both = table_record("a,b\nNaN,inf\n")
    assert compare_tables(both, table_record("a,b\nNaN,inf\n")).equal
    assert not compare_tables(both, table_record("a,b\n1.0,inf\n")).equal
    assert not compare_tables(both, table_record("a,b\nNaN,-inf\n")).equal


def test_quoted_cells_with_commas_are_one_cell() -> None:
    stored = table_record('a,b\n"x, y",1.0\n')
    assert stored["columns"] == ["a", "b"]
    assert compare_tables(stored, table_record('a,b\n"x, y",1.00001\n')).equal
    assert not compare_tables(stored, table_record('a,b\n"x, z",1.0\n')).equal


def _model(table: dict) -> dict:
    return {
        "other": 1,
        "reproducibility": {
            "outputs": [
                {"name": "triangles.csv", "sha256": "ab", "size": "9"},
                {"name": TOLERANCE_FILES[0], **table},
            ]
        },
    }


def test_differences_compare_tables_by_tolerance_and_the_rest_exactly() -> None:
    stored = _model(BASE)
    near = table_record(
        "group,family,shape,se\nMOTOR_OD,pareto2,1.2345679,0.5\nPROPERTY,gamma,2.0,\n"
    )
    assert differences(stored, _model(near)) == []
    far = table_record("group,family,shape,se\nMOTOR_OD,pareto2,1.5,0.5\nPROPERTY,gamma,2.0,\n")
    assert any("shape" in d for d in differences(stored, _model(far)))
    other = _model(BASE)
    other["reproducibility"]["outputs"][0]["sha256"] = "cd"
    assert differences(stored, other) == ["the report data differs outside the tolerance files"]
    assert split_tables(stored)[1][TOLERANCE_FILES[0]] == BASE


def test_the_tolerance_files_are_optimiser_based_outputs_of_mt17_or_mt18(
    default_run: RunResult,
) -> None:
    """A file may be on the list only if MT17 or MT18 writes it (their fits are what differs by
    platform); a blank, repeated or unknown entry fails."""
    assert all(name.strip() and name == name.strip() for name in TOLERANCE_FILES)
    assert len(set(TOLERANCE_FILES)) == len(TOLERANCE_FILES)
    written = set(default_run.severity.files())
    assert set(TOLERANCE_FILES) <= written, sorted(set(TOLERANCE_FILES) - written)
    outputs = {o["name"] for o in default_run.report_data["reproducibility"]["outputs"]}
    assert set(TOLERANCE_FILES) <= outputs
