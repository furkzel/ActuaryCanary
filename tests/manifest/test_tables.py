"""The shared writer of the tier B and severity tables rounds floats to 10 significant digits
(CV06 1.1.0, record 0626)."""

import io
import math
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.manifest.run import (
    SIGNIFICANT_DIGITS,
    round_floats,
    round_significant,
    write_parquet_table,
    write_table,
)
from actuarycanary.spec.loader import load_specs
from actuarycanary.spec.models import ConventionSpec


def test_the_specification_names_the_digits_the_writer_keeps() -> None:
    cv06 = next(f.spec for f in load_specs().files if f.spec.id == "CV06")
    assert isinstance(cv06, ConventionSpec)
    default = next(p for p in cv06.defaults if p.name == "file_significant_digits")
    assert cv06.version == "1.1.0" and default.default == SIGNIFICANT_DIGITS


def significant_digits_ok(value: float) -> bool:
    """True when `value` has no more digits than the rule keeps."""
    return not math.isfinite(value) or float(f"{value:.{SIGNIFICANT_DIGITS - 1}e}") == value


def test_ten_digits_stay_below_the_tolerance_of_the_tightest_benchmark() -> None:
    assert SIGNIFICANT_DIGITS == 10
    values = (1.00000000049, 9.999999999499, 1.5)
    worst = max(abs((round_significant(x) or 0.0) - x) / x for x in values)
    assert worst < 1e-9  # the tightest tolerance in the manifests of the tier B references


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1 / 3, 0.3333333333),
        (2 / 3, 0.6666666667),
        (12345.678901234567, 12345.67890),
        (-0.1042893042670493, -0.1042893043),
        (2.0388489260137388e-10, 2.038848926e-10),
        (75569040.59086789, 75569040.59),
        (1.0, 1.0),
        (0.0, 0.0),
    ],
)
def test_a_float_keeps_ten_significant_digits(value: float, expected: float) -> None:
    assert round_significant(value) == expected


def test_the_last_bits_of_a_platform_do_not_change_the_rounded_value() -> None:
    # two values 1e-14 apart in relative terms, as BLAS kernels and libm produce (record 0626)
    assert round_significant(23862.345139331253) == round_significant(23862.345139331002)
    assert round_significant(-0.1042893042670493) == round_significant(-0.10428930426705008)


def test_null_nan_infinity_and_negative_zero() -> None:
    assert round_significant(None) is None
    assert math.isnan(round_significant(math.nan) or 0.0)
    assert round_significant(math.inf) == math.inf and round_significant(-math.inf) == -math.inf
    assert math.copysign(1.0, round_significant(-0.0) or 1.0) == 1.0


def test_rounding_twice_changes_nothing() -> None:
    once = round_significant(0.1 + 0.2)
    assert once is not None and round_significant(once) == once


def test_only_float_columns_change() -> None:
    frame = pl.DataFrame(
        {"n": [1, 2], "text": ["0.123456789012345", "x"], "x": [1 / 3, None], "flag": [True, None]}
    )
    out = round_floats(frame)
    assert out["x"].to_list() == [0.3333333333, None]
    assert out.drop("x").equals(frame.drop("x"))
    assert out.schema == frame.schema


def test_a_nested_column_is_refused() -> None:
    with pytest.raises(TypeError, match="nested"):
        round_floats(pl.DataFrame({"x": [[1.0, 2.0]]}))


def test_write_table_writes_rounded_cells_and_records_the_bytes(tmp_path: Path) -> None:
    frame = pl.DataFrame({"k": ["a", "b"], "v": [1 / 3, 1e22 / 3]})
    record = write_table(tmp_path, "t.csv", frame)
    data = (tmp_path / "t.csv").read_bytes()
    assert record.size == len(data)
    cells = pl.read_csv(io.BytesIO(data))["v"].to_list()
    assert cells == [0.3333333333, 3.333333333e21]
    assert all(significant_digits_ok(c) for c in cells)


def test_write_parquet_table_writes_rounded_cells(tmp_path: Path) -> None:
    frame = pl.DataFrame({"total": [1 / 3, 2 / 3], "n": [1, 2]})
    record = write_parquet_table(tmp_path, "d.parquet", frame)
    read = pl.read_parquet(tmp_path / "d.parquet")
    assert record.size == (tmp_path / "d.parquet").stat().st_size
    assert read["total"].to_list() == [0.3333333333, 0.6666666667] and read["n"].to_list() == [1, 2]
