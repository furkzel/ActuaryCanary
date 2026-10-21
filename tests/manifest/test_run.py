"""Run id and manifest writing."""

import json
from pathlib import Path

from actuarycanary.manifest.run import (
    InputRecord,
    SheetRecord,
    SpecRecord,
    run_id,
    write_manifest,
    write_output,
)

INPUTS = [InputRecord("claims", "claims.xlsx", 10, "ab" * 32, (SheetRecord("claims", 3),))]
SPECS = [SpecRecord("MT02", "1.0.0", "Chain ladder")]


def test_run_id_depends_on_inputs_specs_settings_and_version() -> None:
    base = run_id(INPUTS, SPECS, {"tail_factor": 1.0}, "0.1.0")
    assert base == run_id(INPUTS, SPECS, {"tail_factor": 1.0}, "0.1.0")
    assert len(base) == 16
    other_input = [InputRecord("claims", "claims.xlsx", 10, "cd" * 32, ())]
    assert run_id(other_input, SPECS, {"tail_factor": 1.0}, "0.1.0") != base
    assert run_id(INPUTS, [SpecRecord("MT02", "1.1.0", "")], {"tail_factor": 1.0}, "0.1.0") != base
    assert run_id(INPUTS, SPECS, {"tail_factor": 1.1}, "0.1.0") != base
    assert run_id(INPUTS, SPECS, {"tail_factor": 1.0}, "0.2.0") != base


def test_manifest_records_outputs_and_is_stable(tmp_path: Path) -> None:
    output = write_output(tmp_path, "a.csv", "x,y\n1,2\n")
    assert output.size == 8
    assert (tmp_path / "a.csv").read_bytes() == b"x,y\n1,2\n"
    arguments = dict(
        run="r1",
        package_version="0.1.0",
        inputs=INPUTS,
        specs=SPECS,
        settings={},
        outputs=[output],
        findings=[],
    )
    first = write_manifest(tmp_path, **arguments).read_bytes()  # type: ignore[arg-type]
    second = write_manifest(tmp_path, **arguments).read_bytes()  # type: ignore[arg-type]
    assert first == second
    manifest = json.loads(first)
    assert manifest["run_id"] == "r1"
    assert manifest["outputs"][0]["sha256"] == output.sha256
    assert manifest["inputs"][0]["sheets"] == [{"name": "claims", "rows": 3}]
