"""Tier B references (decisions 0270-0279): loader, manifests, values and spec coverage.

Spec IDs proved here: MT11-MT22 and AE02 (each reference names its spec IDs in manifest.yaml).
The numbers themselves are recomputed from the inputs in test_tier_b_recompute.py.
"""

import functools
import math
import re
from pathlib import Path

import pytest
import yaml

from tests.benchmarks.load import (
    HAND_TIER_B_DIR,
    TIER_B_DIR,
    load_reference,
    load_values,
    tier_b_folders,
    tier_b_names,
)

SPEC_METHODS = Path(__file__).resolve().parents[2] / "spec" / "methods"
REQUIRED_MANIFEST_KEYS = {
    "id", "spec_ids", "kind", "title", "source", "how_produced", "files", "tolerance_note",
    "produced_on", "checked_by_owner",
}  # fmt: skip
KINDS = {"library_reference", "external_reference", "hand_worked"}


@functools.cache
def _spec_tiers() -> dict[str, str]:
    """Tier of every method spec, read from the text (a full YAML parse costs a second)."""
    tiers = {}
    for path in sorted(SPEC_METHODS.glob("MT*.yaml")):
        text = path.read_text(encoding="utf-8")
        tier = re.search(r"^tier: (\w+)$", text, re.MULTILINE)
        tiers[path.name.split("-")[0]] = tier.group(1) if tier else ""
    return tiers


def test_references_are_found() -> None:
    names = tier_b_names()
    assert len(names) == len(set(names)), "folder names must be unique across both roots"
    assert len(names) == 19, "a reference folder was added or lost: update this count"
    assert {f.parent for f in tier_b_folders()} == {TIER_B_DIR, HAND_TIER_B_DIR}


@pytest.mark.parametrize("name", tier_b_names())
def test_manifest_is_complete(name: str) -> None:
    ref = load_reference(name)
    manifest, folder = ref["manifest"], ref["folder"]
    assert set(manifest) >= REQUIRED_MANIFEST_KEYS
    assert manifest["id"] == name == folder.name
    assert manifest["kind"] in KINDS
    assert isinstance(manifest["checked_by_owner"], bool)
    assert manifest["spec_ids"] and all(isinstance(s, str) for s in manifest["spec_ids"])
    if manifest["kind"] == "hand_worked":
        assert folder.parent == HAND_TIER_B_DIR
        assert manifest["source"]["tool"]
    else:
        assert folder.parent == TIER_B_DIR
        source = manifest["source"]
        assert source["tool"] and source["version"], "tool name and version are part of the record"
        assert source["calls"]
    for spec_id in manifest["spec_ids"]:
        assert list(SPEC_METHODS.glob(f"{spec_id}-*.yaml")) or list(
            SPEC_METHODS.parent.glob(f"*/{spec_id}-*.yaml")
        ), f"{spec_id} is not a spec"


@pytest.mark.parametrize("name", tier_b_names())
def test_files_listed_exist_and_values_are_readable(name: str) -> None:
    ref = load_reference(name)
    folder = ref["folder"]
    for label, relative in ref["manifest"]["files"].items():
        assert (folder / relative).is_file(), f"{name}: {label} -> {relative}"
    values = ref["values"]
    assert values, "values.csv must hold at least one row"
    for (quantity, key), row in values.items():
        assert quantity and key != ""
        assert math.isfinite(row["value"])
        assert row["rel_tol"] >= 0


def test_values_loader_rejects_duplicates(tmp_path: Path) -> None:
    (tmp_path / "values.csv").write_text(
        "quantity,key,value,rel_tol,note\na,1,1.0,0,x\na,1,2.0,0,y\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_values(tmp_path)


def test_values_loader_keeps_keys_as_text(tmp_path: Path) -> None:
    (tmp_path / "values.csv").write_text(
        "quantity,key,value,rel_tol,note\nult,2021,10.5,1e-9,hand\nult,12_24,2.0,0,\n",
        encoding="utf-8",
    )
    values = load_values(tmp_path)
    assert values[("ult", "2021")] == {"value": 10.5, "rel_tol": 1e-9, "note": "hand"}
    assert values[("ult", "12_24")]["value"] == 2.0


def test_every_tier_b_method_spec_has_a_reference() -> None:
    """MT11-MT22 each have at least one reference, or a recorded reason (coverage.yaml)."""
    covered = {s for name in tier_b_names() for s in load_reference(name)["manifest"]["spec_ids"]}
    coverage = yaml.safe_load((TIER_B_DIR / "coverage.yaml").read_text(encoding="utf-8"))
    reasons = coverage["no_reference"] or {}
    tier_b = {spec_id for spec_id, tier in _spec_tiers().items() if tier == "B"}
    assert tier_b == {f"MT{n}" for n in range(11, 23)}, "tier B changed: update coverage.yaml"
    missing = tier_b - covered - set(reasons)
    assert not missing, f"no reference and no recorded reason: {sorted(missing)}"
    for spec_id, reason in reasons.items():
        assert spec_id not in covered, f"{spec_id} has a reference after all: remove its reason"
        assert len(reason) > 20


def test_open_items_name_known_specs() -> None:
    coverage = yaml.safe_load((TIER_B_DIR / "coverage.yaml").read_text(encoding="utf-8"))
    specs = set(_spec_tiers())
    for spec_id, items in coverage["open_items"].items():
        assert spec_id in specs
        assert items and all(len(i) > 20 for i in items)


def test_simulation_rows_carry_their_monte_carlo_tolerance() -> None:
    for name in ("MT11-odp-bootstrap-raa", "MT11-odp-bootstrap-genins"):
        values = load_reference(name)["values"]
        simulated = [(k, v) for k, v in values.items() if k[0].startswith("simulation_")]
        assert len(simulated) >= 10
        for key, row in simulated:
            if key[1] == "sd_analytic":
                continue
            assert 0 < row["rel_tol"] < (1 if "heavy tailed" in row["note"] else 0.1), key
            assert "seed 42" in row["note"] or "other seeds" in row["note"]
