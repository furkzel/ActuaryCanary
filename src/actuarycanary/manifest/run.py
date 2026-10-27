"""Run manifest (blueprint section 12): what went in, which rules and settings, what came out.

The run id is derived from everything that determines the outputs: input fingerprints,
the column mappings applied to them, specification IDs and versions, settings and the
package version. Output fingerprints are recorded in the manifest but are not part of the
id, because the report shows the id.
"""

import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
LINEAGE_FORMAT_KEY = "lineage_format"  # added in 1.1: how lineage.csv is written (decision 0222)
RUN_ID_LENGTH = 16
# Floats of the tier B and severity files are written to this many significant digits (CV06
# 1.1.0, record 0626): the platforms differ in the last bits of optimisers and linear algebra.
SIGNIFICANT_DIGITS = 10


@dataclass(frozen=True)
class SheetRecord:
    name: str
    rows: int


@dataclass(frozen=True)
class InputRecord:
    concept: str
    name: str
    size: int
    sha256: str
    sheets: tuple[SheetRecord, ...]


@dataclass(frozen=True)
class SpecRecord:
    id: str
    version: str
    title: str


@dataclass(frozen=True)
class OutputRecord:
    name: str
    size: int
    sha256: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run_id(
    inputs: list[InputRecord],
    specs: list[SpecRecord],
    settings: dict[str, Any],
    version: str,
    mappings: list[dict[str, Any]] | None = None,
) -> str:
    """`mappings`: per sheet used, its file, sheet, concept and (column, field) pairs."""
    determinants = {
        "inputs": [[i.concept, i.name, i.sha256] for i in inputs],
        "mappings": mappings or [],
        "specs": [[s.id, s.version] for s in specs],
        "settings": settings,
        "version": version,
    }
    digest = hashlib.sha256(_canonical_json(determinants).encode("utf-8")).hexdigest()
    return digest[:RUN_ID_LENGTH]


def write_output_bytes(folder: Path, name: str, data: bytes) -> OutputRecord:
    """Write one binary output file (parquet) and fingerprint it from memory."""
    (folder / name).write_bytes(data)
    return OutputRecord(name, len(data), hashlib.sha256(data).hexdigest())


def write_output(folder: Path, name: str, content: str) -> OutputRecord:
    """Write one output file and fingerprint it from memory, without reading it back."""
    return write_output_bytes(folder, name, content.encode("utf-8"))


def round_significant(value: float | None) -> float | None:
    """`value` to `SIGNIFICANT_DIGITS` significant digits (nearest decimal, as Python formats
    it, so the same on every platform); a negative zero becomes zero; null, NaN and infinity
    stay as they are."""
    if value is None or not math.isfinite(value):
        return value
    return float(f"{value:.{SIGNIFICANT_DIGITS - 1}e}") + 0.0


def round_floats(frame: pl.DataFrame) -> pl.DataFrame:
    """The frame with every 64-bit float cell rounded by `round_significant`. A nested column
    is refused, so that no float can slip past the rule."""
    columns = []
    for name, dtype in frame.schema.items():
        if dtype.is_nested():
            raise TypeError(f"column {name!r} is nested; flatten it before writing")
        if dtype == pl.Float64:
            values = [round_significant(v) for v in frame[name].to_list()]
            columns.append(pl.Series(name, values, dtype=pl.Float64))
    return frame.with_columns(columns)


def write_table(folder: Path, name: str, frame: pl.DataFrame) -> OutputRecord:
    """Write a table of the tier B or severity methods as csv, floats rounded (record 0626).
    Every new output file goes through here (or `write_parquet_table`), not through
    `write_csv`, so that the rule stays in one place."""
    return write_output(folder, name, round_floats(frame).write_csv())


def write_parquet_table(folder: Path, name: str, frame: pl.DataFrame) -> OutputRecord:
    """Write a table as parquet, floats rounded as in `write_table`."""
    buffer = io.BytesIO()
    round_floats(frame).write_parquet(buffer, compression="zstd", statistics=False)
    return write_output_bytes(folder, name, buffer.getvalue())


def write_manifest(
    folder: Path,
    *,
    run: str,
    package_version: str,
    inputs: list[InputRecord],
    specs: list[SpecRecord],
    settings: dict[str, Any],
    outputs: list[OutputRecord],
    findings: list[dict[str, Any]],
    lineage_format: int | None = None,
    mapping_profiles: list[dict[str, Any]] | None = None,
    tables_not_used: list[dict[str, Any]] | None = None,
    assumptions: list[dict[str, Any]] | None = None,
    randomness: list[dict[str, Any]] | None = None,
) -> Path:
    """Write manifest.json; no clock time, so a rerun on the same inputs writes the same file."""
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run,
        "software": {"actuarycanary": package_version},
        "inputs": [asdict(i) for i in inputs],
        "mapping_profiles": mapping_profiles or [],  # how each sheet used was read
        "tables_not_used": tables_not_used or [],
        "specs": [asdict(s) for s in specs],
        "settings": settings,
        "assumptions": assumptions or [],  # every judgement in force (blueprint 12)
        "randomness": randomness or [],  # seeds of the stochastic steps
        "data_findings": findings,
        "outputs": [asdict(o) for o in outputs],
    }
    if lineage_format is not None:
        manifest[LINEAGE_FORMAT_KEY] = lineage_format
    path = folder / MANIFEST_NAME
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
