"""Run manifest (blueprint section 12): what went in, which rules and settings, what came out.

The run id is derived from everything that determines the outputs: input fingerprints,
the column mappings applied to them, specification IDs and versions, settings and the
package version. Output fingerprints are recorded in the manifest but are not part of the
id, because the report shows the id.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
RUN_ID_LENGTH = 16


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


def write_output(folder: Path, name: str, content: str) -> OutputRecord:
    """Write one output file and fingerprint it from memory, without reading it back."""
    data = content.encode("utf-8")
    (folder / name).write_bytes(data)
    return OutputRecord(name, len(data), hashlib.sha256(data).hexdigest())


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
    mapping_profiles: list[dict[str, Any]] | None = None,
    tables_not_used: list[dict[str, Any]] | None = None,
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
        "randomness": [],  # no stochastic step ran
        "data_findings": findings,
        "outputs": [asdict(o) for o in outputs],
    }
    path = folder / MANIFEST_NAME
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
