"""End to end on the tiny baseline: the run completes and reproduces its outputs."""

import json
import shutil
from pathlib import Path

import pytest

from actuarycanary.pipeline import InputError, RunSettings, run
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSettings

BASELINE = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache")


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_baseline_tiny_runs_and_reproduces(tmp_path: Path, cache: Path) -> None:
    first = run(BASELINE, tmp_path / "a", cache_dir=cache)
    second = run(BASELINE, tmp_path / "b", cache_dir=cache)
    assert first.run_id == second.run_id
    assert first.folder == tmp_path / "a" / first.run_id
    one, two = _manifest(first.manifest), _manifest(second.manifest)
    assert one["outputs"] == two["outputs"]
    assert first.manifest.read_bytes() == second.manifest.read_bytes()
    assert [o["name"] for o in one["outputs"]] == [
        "report.html",
        "triangles.csv",
        "factors.csv",
        "chain_ladder.csv",
    ]
    assert [i["name"] for i in one["inputs"]] == ["claim_valuations.xlsx", "claims.xlsx"]
    assert {"MT01", "MT02", "claim_valuations", "claims"} <= {s["id"] for s in one["specs"]}
    assert one["settings"]["triangles"]["origin_period"] == "YEAR"
    rules = {f["rule"] for f in one["data_findings"]}
    assert {"DV-CLV-03", "DV-CLV-04", "DV-CLV-06"} <= rules  # injected faults are found
    groups = {g.group for g in first.reserving.groups}
    assert groups == {
        ("LIFE", "GROUP_TERM_LIFE"),
        ("NON_LIFE", "MOTOR_OD"),
        ("NON_LIFE", "MOTOR_TPL"),
        ("NON_LIFE", "PROPERTY"),
    }


def test_settings_change_the_run_id(tmp_path: Path, cache: Path) -> None:
    yearly = run(BASELINE, tmp_path / "y", cache_dir=cache)
    quarterly = run(
        BASELINE,
        tmp_path / "q",
        RunSettings(triangles=TriangleSettings(development_period=Period.QUARTER)),
        cache_dir=cache,
    )
    assert quarterly.run_id != yearly.run_id
    assert quarterly.reserving.groups[0].triangles["paid"].ages[:2] == (3, 6)


def test_claim_valuations_alone_use_proxy_origins(tmp_path: Path, cache: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    result = run(folder, tmp_path / "out", cache_dir=cache)
    assert result.reserving.triangles.origin_basis == "first_valuation (proxy)"
    assert "claims" not in {s["id"] for s in _manifest(result.manifest)["specs"]}


def test_missing_claim_valuations_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="claim_valuations.xlsx"):
        run(tmp_path, tmp_path / "out", cache_dir=None)
