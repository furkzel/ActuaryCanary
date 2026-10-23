"""The two lineage formats: format 2 holds the same rows as format 1 in far fewer bytes, and
either one can be turned into the other without a difference (decision 0222)."""

from pathlib import Path

import polars as pl
import pytest

from actuarycanary.measures.lineage import (
    ATOMS_NAME,
    FORMAT_1,
    FORMAT_2,
    LINEAGE_NAME,
    Lineage,
    build_lineage,
    read_lineage,
    to_format1,
)
from actuarycanary.measures.output import UNIT, lineage_table
from actuarycanary.structures.periods import Period
from tests.measures.helpers import make_inputs, measure
from tests.quality.builders import cv, policy, premium

V1_COLUMNS = ["measure", "version", "view", "row", "concept", "file", "sheet", "rows", "count"]


def _units(lines: list[tuple]) -> pl.DataFrame:
    """Format 1 lines with their unit: (unit, row, file, sheet, rows, count)."""
    return pl.DataFrame(
        {
            UNIT: [x[0] for x in lines],
            "measure": ["CL01"] * len(lines),
            "version": ["1.0.0"] * len(lines),
            "view": ["all"] * len(lines),
            "row": [x[1] for x in lines],
            "concept": ["claim_valuations"] * len(lines),
            "file": [x[2] for x in lines],
            "sheet": [x[3] for x in lines],
            "rows": [x[4] for x in lines],
            "count": [x[5] for x in lines],
        },
        schema_overrides={UNIT: pl.Int32, "row": pl.UInt32, "count": pl.UInt32},
    )


def test_atoms_are_the_row_sets_cited_by_exactly_the_same_values() -> None:
    from actuarycanary.measures.lineage import _atomise

    units = _units(
        [
            (0, 0, "a.xlsx", "s", "2-9", 8),  # rows 2-9
            (0, 1, "a.xlsx", "s", "4-6", 3),  # rows 4-6, inside the first value
            (1, 0, "a.xlsx", "s", "2-9", 8),  # a second result with the same rows
            (1, 0, "b.xlsx", "s", "2-3", 2),  # and rows of another file
        ]
    )
    lineage = _atomise(units)
    assert lineage.format == FORMAT_2 and lineage.atoms is not None
    atoms = lineage.atoms.sort("atom")
    assert atoms.select("file", "rows", "count").rows() == [
        ("a.xlsx", "2-3;7-9", 5),  # cited by the whole-range values only
        ("a.xlsx", "4-6", 3),  # cited by the inner value as well
        ("b.xlsx", "2-3", 2),
    ]
    assert lineage.values.select("row", "atoms", "count").rows() == [
        (0, "0-1", 8),
        (1, "1", 3),
        (0, "0-2", 10),
    ]


def test_format_2_rebuilds_format_1_line_for_line() -> None:
    from actuarycanary.measures.lineage import _atomise

    units = _units(
        [
            (0, 0, "a.xlsx", "s", "2-9;12", 9),
            (0, 0, "a.xlsx", "t", "2", 1),
            (0, 1, "a.xlsx", "s", "5", 1),
            # the same measure and view again with the same row number: another unit, another rows
            (1, 0, "a.xlsx", "s", "5;9", 2),
            (2, 0, "b.xlsx", "s", "3-4", 2),
        ]
    )
    again = to_format1(_atomise(units))
    expected = units.drop(UNIT)
    assert again.select(V1_COLUMNS).to_dicts() == expected.select(V1_COLUMNS).to_dicts()


def test_an_empty_lineage_converts_both_ways() -> None:
    empty = build_lineage([], make_inputs({"claim_valuations": [cv(1)]}), FORMAT_2)
    assert empty.values.height == 0 and empty.atoms is not None and empty.atoms.height == 0
    assert to_format1(empty).height == 0
    assert (
        build_lineage([], make_inputs({"claim_valuations": [cv(1)]}), FORMAT_1).values.height == 0
    )


def test_unknown_format_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown lineage format 3"):
        build_lineage([], make_inputs({"claim_valuations": [cv(1)]}), 3)


def _results():
    rows = [cv(m, claim_id=f"K{i}", paid_to_date=float(m)) for m in (1, 2, 3) for i in range(6)]
    inputs = make_inputs(
        {
            "claim_valuations": rows,
            "premiums": [premium(transaction_id=f"T{i}") for i in range(5)],
            "policies": [policy()],
        }
    )
    results = [
        measure(inputs, "CL01", "origin_period"),
        measure(inputs, "CL01", "calendar_period", period=Period.MONTH),
        measure(inputs, "CL03", "origin_period"),
        measure(inputs, "PR02", "segment"),
    ]
    return inputs, results


def test_built_from_results_format_2_equals_format_1_and_is_smaller() -> None:
    inputs, results = _results()
    one = build_lineage(results, inputs, FORMAT_1)
    two = build_lineage(results, inputs, FORMAT_2)
    assert one.values.to_dicts() == lineage_table(results, inputs).to_dicts()
    assert one.values.height > 0
    assert to_format1(two).select(V1_COLUMNS).to_dicts() == one.values.to_dicts()
    assert two.summary()["rows_cited"] == one.summary()["rows_cited"]
    assert two.summary()["traced_values"] == one.summary()["traced_values"]
    assert two.atoms is not None and two.atoms.height > 0


def test_values_that_share_rows_cost_the_rows_once_in_format_2() -> None:
    from actuarycanary.measures.lineage import _atomise

    # 40 values, each citing rows of the same two alternating sets of 199 rows in a file
    odd = ";".join(str(r) for r in range(3, 400, 2))
    even = ";".join(str(r) for r in range(2, 400, 2))
    lines = [(unit, 0, "a.xlsx", "s", odd if unit % 2 else even, 199) for unit in range(40)]
    units = _units(lines)
    two = _atomise(units)
    assert two.atoms is not None
    assert two.atoms.height == 2
    size_1 = len(units.drop(UNIT).write_csv())
    size_2 = len(two.values.write_csv()) + len(two.atoms.write_csv())
    assert size_2 * 4 < size_1  # the rows are listed twice, not forty times
    assert to_format1(two).select(V1_COLUMNS).to_dicts() == units.drop(UNIT).to_dicts()


def test_files_are_read_back_in_whichever_format_they_were_written(tmp_path: Path) -> None:
    inputs, results = _results()
    for number in (FORMAT_1, FORMAT_2):
        folder = tmp_path / str(number)
        folder.mkdir()
        written = build_lineage(results, inputs, number)
        for name, text in written.files().items():
            (folder / name).write_text(text, encoding="utf-8", newline="\n")
        read = read_lineage(folder)
        assert read.format == number
        assert (read.atoms is not None) == (number == FORMAT_2)
        assert sorted(written.files()) == sorted([LINEAGE_NAME, *([ATOMS_NAME] * (number == 2))])
    one, two = read_lineage(tmp_path / "1"), read_lineage(tmp_path / "2")
    as_text = [pl.col(c).cast(pl.String) for c in V1_COLUMNS]
    assert to_format1(two).select(as_text).to_dicts() == to_format1(one).select(as_text).to_dicts()
    assert (
        isinstance(one, Lineage) and one.summary()["format"] == 1 and two.summary()["format"] == 2
    )
