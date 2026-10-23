import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "compare_manifests", ROOT / "packaging" / "compare_manifests.py"
)
assert _spec is not None and _spec.loader is not None
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)


def manifest(run_id: str = "aa", hashes: dict[str, str] | None = None) -> dict:
    outputs = [
        {"name": n, "sha256": h} for n, h in (hashes or {"a.csv": "1", "b.csv": "2"}).items()
    ]
    return {"run_id": run_id, "inputs": [], "specs": [], "settings": {}, "outputs": outputs}


def test_equal_manifests_have_no_difference() -> None:
    assert compare.differences(manifest(), manifest()) == []


def test_another_run_id_is_a_difference() -> None:
    assert compare.differences(manifest(), manifest("bb")) == ["run_id differs"]


def test_one_output_with_another_hash_is_named() -> None:
    other = manifest(hashes={"a.csv": "1", "b.csv": "3"})
    assert compare.differences(manifest(), other) == ["output b.csv has another SHA-256"]


def test_an_output_in_only_one_manifest_is_named() -> None:
    other = manifest(hashes={"a.csv": "1"})
    assert compare.differences(manifest(), other) == ["output b.csv is in only one manifest"]


def test_the_bundle_definition_requires_the_demo_data() -> None:
    spec = (ROOT / "packaging" / "canary.spec").read_text(encoding="utf-8")
    assert '"examples" / "demo"' in spec and "SystemExit" in spec
    assert (ROOT / "examples" / "demo" / "claim_valuations.xlsx").is_file()
