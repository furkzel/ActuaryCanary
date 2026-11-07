# pyright: reportOptionalMemberAccess=false
"""M12 and the discounted value basis through a whole run (records 0320 to 0329).

Spec IDs proved: M12, RS03, RS04, RS05, CV10, interest_rates, CV02. A folder is the six workbooks
of the tiny baseline with an interest_rates workbook beside them (a flat 30 per cent TRY curve,
a flat 3 per cent EUR curve). The tiny triangles are too small for the bootstrap, so the run
shows the expected cash flows and their present value; the bootstrap path is run on the
demonstration folder (slow).
"""

import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from actuarycanary.cli import app
from actuarycanary.convert.bases import ValueBasis
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.pipeline import InputError, RunResult, RunSettings, run
from actuarycanary.structures.triangles import TriangleSettings
from tests.conftest import BASELINE_TINY

pytestmark = pytest.mark.slow

DEMO = Path(__file__).parent.parent / "examples" / "demo"
CUT_OFF = date(2025, 12, 31)


def write_rates(folder: Path, rate: float = 0.30) -> None:
    rows = [
        {
            "curve_id": curve,
            "date": day,
            "tenor_months": months,
            "rate": value,
            "rate_type": "SPOT",
            "compounding": "ANNUAL",
            "currency": currency,
            "source": "TEST",
        }
        for curve, currency, value in (("TRY_GOV", "TRY", rate), ("EUR_SWAP", "EUR", 0.03))
        for day in (date(2025, 11, 30), CUT_OFF)
        for months in (12, 60, 120)
    ]
    pl.DataFrame(rows).write_excel(folder / "interest_rates.xlsx", worksheet="rates")


@pytest.fixture(scope="module")
def folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("with_rates")
    for file in BASELINE_TINY.glob("*.xlsx"):
        shutil.copy(file, target / file.name)
    write_rates(target)
    return target


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache_m12")


def go(folder: Path, out: Path, cache: Path, **settings) -> RunResult:  # noqa: ANN003
    return run(folder, out, RunSettings(**settings), cache_dir=cache)


def discounted(**kwargs) -> dict:  # noqa: ANN003
    return {
        "triangles": TriangleSettings(value_basis=ValueBasis.DISCOUNTED),
        "discount": DiscountSettings(curve_id="TRY_GOV", **kwargs),
    }


@pytest.fixture(scope="module")
def nominal_run(folder: Path, tmp_path_factory: pytest.TempPathFactory, cache: Path) -> RunResult:
    return go(folder, tmp_path_factory.mktemp("nominal"), cache)


@pytest.fixture(scope="module")
def discounted_run(
    folder: Path, tmp_path_factory: pytest.TempPathFactory, cache: Path
) -> RunResult:
    return go(folder, tmp_path_factory.mktemp("discounted"), cache, **discounted())


def manifest(result: RunResult) -> dict:
    return json.loads(result.manifest.read_text(encoding="utf-8"))


def test_interest_rates_are_read_as_a_concept_and_checked(nominal_run: RunResult) -> None:
    concepts = {t.concept for t in nominal_run.tables}
    assert "interest_rates" in concepts
    assert "interest_rates" in {c.concept for c in nominal_run.quality.coverage if c.loaded}
    inputs = {i["concept"] for i in manifest(nominal_run)["inputs"]}
    assert "interest_rates" in inputs


def test_without_a_named_curve_m12_shows_no_discounted_figures_and_says_why(
    nominal_run: RunResult,
) -> None:
    m12 = nominal_run.analysis.get("M12")
    assert m12.state.value == "limited"
    assert any("no curve is named" in reason for reason in m12.reasons)
    assert not nominal_run.discount.available
    used = manifest(nominal_run)["settings"]["discount_used"]
    assert used["available"] is False and "no curve is named" in used["reason"]
    risk = pl.read_csv(nominal_run.folder / "risk_measures.csv")
    assert risk.filter(pl.col("value_basis") == "DISCOUNTED").height == 0
    assert not (nominal_run.folder / "discount_curve.csv").exists()


def test_the_discounted_basis_discounts_with_the_named_curve(
    nominal_run: RunResult, discounted_run: RunResult
) -> None:
    assert discounted_run.discount.available
    assert discounted_run.discount.curve.curve_id == "TRY_GOV"
    assert discounted_run.discount.curve.curve_date == CUT_OFF
    risk = pl.read_csv(discounted_run.folder / "risk_measures.csv")
    expected = risk.filter(pl.col("source") == "expected_cash_flows")
    assert expected.height > 0 and set(expected["value_basis"]) == {"DISCOUNTED"}
    # every origin's flows have the sign of its selected unpaid, so discounting moves it to zero
    assert (expected["mean"].abs() <= expected["nominal_mean"].abs() + 1e-6).all()
    assert (expected["mean"].abs() < expected["nominal_mean"].abs()).any()
    effect = expected["nominal_mean"] - expected["mean"]
    assert effect.to_list() == pytest.approx(
        expected["discount_effect"].to_list(), rel=1e-8, abs=1e-6
    )
    curve = pl.read_csv(discounted_run.folder / "discount_curve.csv")
    assert curve["curve_id"].unique().to_list() == ["TRY_GOV"] and curve.height >= 3
    # the amounts of the past stay nominal (CV10): the triangles and the chain ladder do not move
    a = pl.read_csv(nominal_run.folder / "chain_ladder.csv")
    b = pl.read_csv(discounted_run.folder / "chain_ladder.csv")
    assert a.equals(b)
    assert discounted_run.run_id != nominal_run.run_id


def test_the_manifest_records_the_curve_the_date_and_the_basis(discounted_run: RunResult) -> None:
    settings = manifest(discounted_run)["settings"]
    assert settings["bases"]["value"] == "DISCOUNTED"
    assert settings["discount"]["curve_id"] == "TRY_GOV"
    used = settings["discount_used"]
    assert (used["curve_id_used"], used["curve_date_used"]) == ("TRY_GOV", "2025-12-31")
    assert used["discount_date_used"] == "2025-12-31" and used["source"] == "TEST"
    assert used["currency"] == "TRY" and used["curve_age_days"] == 0
    spec_ids = {s["id"] for s in manifest(discounted_run)["specs"]}
    assert {"CV10", "interest_rates", "M12", "RS04", "RS05"} <= spec_ids
    entries = {(a["method"], a["name"]): a for a in manifest(discounted_run)["assumptions"]}
    assert entries[("CV10", "curve_id")]["value"] == "TRY_GOV"
    assert entries[("CV10", "curve_id")]["who"] == "run settings"
    assert entries[("RS05", "line_correlation")]["value"] == 0.0


def test_the_discount_date_and_the_curve_change_the_run_id(
    folder: Path, tmp_path: Path, cache: Path, discounted_run: RunResult
) -> None:
    other_date = go(folder, tmp_path / "a", cache, **discounted(discount_date=date(2025, 11, 30)))
    assert other_date.run_id != discounted_run.run_id
    assert other_date.discount.discount_date == date(2025, 11, 30)
    assert other_date.discount.curve.curve_date == date(2025, 11, 30)
    again = go(folder, tmp_path / "b", cache, **discounted())
    assert again.run_id == discounted_run.run_id


def test_the_measures_rs04_and_rs05_are_in_measures_csv_on_the_discounted_basis(
    discounted_run: RunResult,
) -> None:
    values = pl.read_csv(discounted_run.folder / "measures.csv")
    rs04 = values.filter(pl.col("measure") == "RS04")
    assert rs04.height > 0 and set(rs04["basis"]) == {"GROSS, REPORTING, DISCOUNTED"}
    # a measure of the past is shown nominal, and the note says so
    past = values.filter(pl.col("measure") == "CL01")
    assert set(past["basis"]) == {"GROSS, REPORTING, NOMINAL"}
    said = [
        note
        for result in discounted_run.analysis.results()
        if result.measure == "CL01"
        for note in result.notes
    ]
    assert any("NOMINAL only" in note for note in said)


def test_the_discounted_basis_without_a_curve_cannot_run(
    folder: Path, tmp_path: Path, cache: Path
) -> None:
    with pytest.raises(InputError, match="needs a curve.*no curve is named"):
        go(folder, tmp_path, cache, triangles=TriangleSettings(value_basis=ValueBasis.DISCOUNTED))
    with pytest.raises(InputError, match="EUR"):
        go(
            folder, tmp_path, cache,
            triangles=TriangleSettings(value_basis=ValueBasis.DISCOUNTED),
            discount=DiscountSettings(curve_id="EUR_SWAP"),
        )  # fmt: skip


def test_a_curve_can_be_named_on_the_nominal_basis_too(
    folder: Path, tmp_path: Path, cache: Path
) -> None:
    result = go(folder, tmp_path, cache, discount=DiscountSettings(curve_id="TRY_GOV"))
    assert result.discount.available
    values = pl.read_csv(result.folder / "measures.csv")
    assert set(values.filter(pl.col("measure") == "RS04")["basis"]) == {
        "GROSS, REPORTING, DISCOUNTED"
    }
    assert manifest(result)["settings"]["bases"]["value"] == "NOMINAL"


def test_the_command_line_takes_value_curve_and_discount_date(folder: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    args = [
        "run", str(folder), "--yes", "--out", str(out), "--value", "discounted",
        "--curve", "TRY_GOV", "--discount-date", "2025-11-30",
    ]  # fmt: skip
    answer = CliRunner().invoke(app, args)
    assert answer.exit_code == 0, answer.output
    assert "M12 Uncertainty and risk" in answer.output
    written = json.loads(next(out.iterdir()).joinpath("manifest.json").read_text(encoding="utf-8"))
    assert written["settings"]["discount"]["discount_date"] == "2025-11-30"
    refused = CliRunner().invoke(
        app, ["run", str(folder), "--yes", "--out", str(out), "--value", "discounted"]
    )
    assert refused.exit_code == 1 and "needs a curve" in refused.output.replace("\n", " ")


def test_the_demonstration_data_gives_the_bootstrap_range_and_its_discounted_distribution(
    tmp_path: Path, cache: Path
) -> None:
    folder = tmp_path / "demo"
    shutil.copytree(DEMO, folder, ignore=shutil.ignore_patterns("report"))
    write_rates(folder)
    result = go(folder, tmp_path / "out", cache, **discounted())
    risk = pl.read_csv(result.folder / "risk_measures.csv")
    boot = risk.filter((pl.col("source") == "bootstrap") & (pl.col("origin_period") == "Total"))
    assert set(boot["value_basis"]) == {"NOMINAL", "DISCOUNTED"}
    nominal = boot.filter(pl.col("value_basis") == "NOMINAL").row(0, named=True)
    present = boot.filter(pl.col("value_basis") == "DISCOUNTED").row(0, named=True)
    assert present["mean"] < nominal["mean"] and present["value_at_risk"] < nominal["value_at_risk"]
    assert nominal["simulations"] == 10_000
    assert "mean of the simulated values" in nominal["estimator"]
    distribution = pl.read_parquet(result.folder / "risk_distribution.parquet")
    assert distribution.height == 10_000 and "simulation" in distribution.columns
    assert any(c.endswith("(discounted)") for c in distribution.columns)
    assert result.analysis.get("M12").state.value in ("ran", "limited")
