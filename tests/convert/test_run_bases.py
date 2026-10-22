"""Runs on the tiny baseline with the net, converted and inflation-adjusted bases."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from actuarycanary.cli import app
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.pipeline import InputError, RunResult, RunSettings, run
from actuarycanary.structures.triangles import OriginAxis, TriangleSettings

BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"
CACHE = Path(".cache")  # shared with the other tests that open the fixture spreadsheets

pytestmark = pytest.mark.integration


def _run(tmp_path: Path, name: str, currency: bool = False, **triangles) -> RunResult:
    settings = RunSettings(
        reporting_currency="TRY" if currency else None,
        use_market=currency,
        triangles=TriangleSettings(**triangles),
    )
    return run(BASELINE, tmp_path / name, settings, cache_dir=CACHE)


def _manifest(result: RunResult) -> dict:
    return json.loads(result.manifest.read_text(encoding="utf-8"))


def _latest_incurred(result: RunResult) -> float:
    return sum(float(g.totals().incurred) for g in result.reserving.groups)


@pytest.mark.slow
def test_done_when_net_try_inflation_adjusted_runs_through_the_command(tmp_path: Path) -> None:
    arguments = ["run", str(BASELINE), "--out", str(tmp_path), "--yes"]
    arguments += ["--basis", "net", "--currency", "TRY", "--value", "inflation-adjusted"]
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert "NET, INFLATION_ADJUSTED" in result.output
    [report] = tmp_path.glob("*/report.html")
    html = report.read_text(encoding="utf-8")
    assert "NET, INFLATION_ADJUSTED" in html
    assert "prices of 2025-12-31 (CPI_TR)" in html
    manifest = json.loads((report.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["settings"]["bases"] == {
        "reinsurance": "NET",
        "currency": "REPORTING",
        "currency_conversion": "market",
        "value": "INFLATION_ADJUSTED",
    }
    assert manifest["settings"]["triangles"]["value_date_used"] == "2025-12-31"
    assert {"CV02", "market"} <= {s["id"] for s in manifest["specs"]}
    assert "market.xlsx" in {i["name"] for i in manifest["inputs"]}


@pytest.mark.slow
def test_the_adjusted_run_is_reproducible(tmp_path: Path) -> None:
    one = _run(tmp_path, "a", True, value_basis=ValueBasis.INFLATION_ADJUSTED)
    two = _run(tmp_path, "b", True, value_basis=ValueBasis.INFLATION_ADJUSTED)
    assert one.run_id == two.run_id
    assert one.manifest.read_bytes() == two.manifest.read_bytes()
    assert (one.folder / "triangles.csv").read_bytes() == (
        two.folder / "triangles.csv"
    ).read_bytes()


@pytest.mark.slow
def test_bases_change_the_run_id_and_the_numbers(tmp_path: Path) -> None:
    default = _run(tmp_path, "gross")
    net = _run(tmp_path, "net", reinsurance_basis=ReinsuranceBasis.NET)
    converted = _run(tmp_path, "try", True)
    adjusted = _run(tmp_path, "adj", True, value_basis=ValueBasis.INFLATION_ADJUSTED)
    assert len({default.run_id, net.run_id, converted.run_id, adjusted.run_id}) == 4
    assert _latest_incurred(net) < _latest_incurred(default)  # the tiny baseline cedes claims
    assert _latest_incurred(adjusted) > 1.3 * _latest_incurred(converted)  # high inflation


@pytest.mark.slow
def test_currency_conversion_brings_foreign_claims_into_the_triangles(tmp_path: Path) -> None:
    apart = _run(tmp_path, "apart")
    converted = _run(tmp_path, "converted", True)
    # DV-CLV-03 (1.2.0): the four empty currencies of the fixture take the currency of their claim
    assert apart.reserving.triangles.not_converted["currency"].to_list() == ["USD"]
    assert converted.reserving.triangles.not_converted["currency"].to_list() == []
    # market is read for the quality checks in every run (P06), so its spec is listed in both;
    # only the conversion differs
    assert "market" in {s["id"] for s in _manifest(converted)["specs"]}
    assert "market" in {s["id"] for s in _manifest(apart)["specs"]}
    assert _manifest(converted)["settings"]["bases"]["currency_conversion"] == "market"
    assert _manifest(apart)["settings"]["bases"]["currency_conversion"] == "none"


@pytest.mark.slow
def test_a_ceded_run_shows_ceded_amounts_only(tmp_path: Path) -> None:
    gross = _run(tmp_path, "gross")
    ceded = _run(tmp_path, "ceded", reinsurance_basis=ReinsuranceBasis.CEDED)
    assert 0 < _latest_incurred(ceded) < _latest_incurred(gross)


@pytest.mark.slow
def test_the_underwriting_origin_axis_reads_policies(tmp_path: Path) -> None:
    result = _run(tmp_path, "uw", origin_axis=OriginAxis.UNDERWRITING)
    assert result.reserving.triangles.origin_basis == "underwriting"
    assert "policies" in {s["id"] for s in _manifest(result)["specs"]}


def test_the_adjusted_basis_without_market_data_stops_with_a_message(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(BASELINE / "claim_valuations.xlsx", folder / "claim_valuations.xlsx")
    settings = RunSettings(triangles=TriangleSettings(value_basis=ValueBasis.INFLATION_ADJUSTED))
    with pytest.raises(InputError, match="needs a price index and exchange rates"):
        run(folder, tmp_path / "out", settings, cache_dir=CACHE)
