"""The ORIGINAL currency view of a run (CV01 1.2.0, record 0225): nothing is converted and
amounts of different currencies are never added."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.currency import IDENTITY_TARGET, Rule, lookup_rates
from actuarycanary.convert.views import (
    ORIGINAL,
    REPORTING,
    VIEWS,
    currency_of,
    identity_rates,
    line_in,
    split_claims,
    split_policies,
)
from actuarycanary.measures.model import CurrencyView
from actuarycanary.modules.runner import request_for
from actuarycanary.pipeline import RunResult, RunSettings, run
from actuarycanary.spec.loader import load_specs

BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"
SPECS = load_specs()


def _valuations() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "claim_id": ["A", "A", "B", "C", "D"],
            "currency": ["TRY", "TRY", "USD", "UNKNOWN", None],
        }
    )


def test_a_claim_takes_the_currency_of_its_valuations_into_its_line() -> None:
    claims = pl.DataFrame(
        {
            "claim_id": ["A", "B", "C", "D", "E"],
            "line": ["MOTOR", "MOTOR", "MOTOR", None, "MOTOR"],
        }
    )
    split = split_claims(claims, _valuations())
    # C has an unknown currency, E no valuation: both keep their line
    assert split["line"].to_list() == [
        "MOTOR [TRY]",
        "MOTOR [USD]",
        "MOTOR",
        None,
        "MOTOR",
    ]
    assert split["claim_id"].to_list() == claims["claim_id"].to_list()  # order kept


def test_a_policy_takes_its_own_currency_into_its_line() -> None:
    policies = pl.DataFrame(
        {
            "policy_id": ["1", "2", "3"],
            "line": ["HOME", "HOME", None],
            "currency": ["TRY", "EUR", "USD"],
        }
    )
    assert split_policies(policies)["line"].to_list() == [
        "HOME [TRY]",
        "HOME [EUR]",
        "UNKNOWN [USD]",
    ]
    assert split_policies(policies.drop("currency")).columns == ["policy_id", "line"]


def test_the_currency_of_a_line_is_read_back_from_its_name() -> None:
    assert line_in("MOTOR_OD", "USD") == "MOTOR_OD [USD]"
    assert currency_of("MOTOR_OD [USD]") == "USD"
    assert currency_of("MOTOR_OD") == ""
    assert VIEWS == (REPORTING, ORIGINAL)


def test_every_rate_of_the_original_view_is_one() -> None:
    assert identity_rates(["TRY", "USD"]).rates == {"TRY": 1.0, "USD": 1.0}
    keys = pl.DataFrame({"currency": ["USD", "EUR"], "day": [date(2024, 1, 5)] * 2})
    found = lookup_rates(None, IDENTITY_TARGET, keys, Rule.FLOW)
    assert found.sort("currency")["rate"].to_list() == [1.0, 1.0]
    assert lookup_rates(None, "TRY", keys, Rule.FLOW)["rate"].null_count() == 2  # no market


def test_amount_measures_are_asked_in_the_original_view_and_the_others_stay_as_they_are() -> None:
    args = (("calendar_period",), None, ReinsuranceBasis.GROSS, ValueBasis.NOMINAL)
    from actuarycanary.structures.periods import Period

    def currency(measure: str, view: CurrencyView) -> CurrencyView:
        request, _ = request_for(
            SPECS.measures[measure], args[0], Period.YEAR, args[2], args[3], view
        )
        return request.basis.currency

    assert currency("PR01", CurrencyView.REPORTING) is CurrencyView.REPORTING
    assert currency("PR01", CurrencyView.ORIGINAL) is CurrencyView.ORIGINAL
    assert currency("EX01", CurrencyView.ORIGINAL) is CurrencyView.ORIGINAL
    # defined in REPORTING only: its lines are one currency each, so the identity rate serves
    assert currency("RT01", CurrencyView.ORIGINAL) is CurrencyView.REPORTING


def test_the_settings_know_two_views_and_say_why_functional_is_not_one() -> None:
    assert RunSettings().currency_view == REPORTING
    assert RunSettings(currency_view=ORIGINAL).currency_view == ORIGINAL
    with pytest.raises(ValueError, match="FUNCTIONAL equals REPORTING"):
        RunSettings(currency_view="FUNCTIONAL")


@pytest.fixture(scope="module")
def original(tmp_path_factory: pytest.TempPathFactory, cache: Path) -> RunResult:
    settings = RunSettings(currency_view=ORIGINAL)
    return run(BASELINE, tmp_path_factory.mktemp("original"), settings, cache_dir=cache)


@pytest.mark.slow
def test_a_run_in_the_original_view_keeps_every_line_in_one_currency(
    original: RunResult, default_run: RunResult
) -> None:
    lines = [g.group[1] for g in original.reserving.groups]
    assert all(currency_of(line) for line in lines)
    assert "PROPERTY [USD]" in lines and "PROPERTY [TRY]" in lines
    # the one USD claim is not converted: its paid amount is the amount in the file
    usd = next(g for g in original.reserving.groups if g.group[1] == "PROPERTY [USD]")
    converted = next(g for g in default_run.reserving.groups if g.group[1] == "PROPERTY")
    assert usd.totals().paid < 1.0  # dollars, not liras
    # a line without a foreign claim has the numbers of the reporting view
    pairs = [("MOTOR_OD [TRY]", "MOTOR_OD"), ("MOTOR_TPL [TRY]", "MOTOR_TPL")]
    for split_line, line in pairs:
        a = next(g for g in original.reserving.groups if g.group[1] == split_line)
        b = next(g for g in default_run.reserving.groups if g.group[1] == line)
        assert a.totals().paid == pytest.approx(b.totals().paid)
        assert a.totals().incurred == pytest.approx(b.totals().incurred)
    assert converted.totals().paid > usd.totals().paid


@pytest.mark.slow
def test_the_original_view_enters_the_run_id_and_the_page_says_how_amounts_are_kept_apart(
    original: RunResult, default_run: RunResult
) -> None:
    assert original.run_id != default_run.run_id
    page = original.report.read_text(encoding="utf-8")
    assert "ORIGINAL: nothing is converted" in page
    manifest = (original.folder / "manifest.json").read_text(encoding="utf-8")
    assert '"currency": "ORIGINAL"' in manifest and '"currency_conversion": "none"' in manifest
    tiles = {t["segment"]: t["tiles"] for t in original.report_data["tiles"]}
    # LIFE has one currency: its tiles stand; NON_LIFE has two and is not added
    assert len(tiles["LIFE"]) == 4
    assert [t["label"] for t in tiles["NON_LIFE"]] == ["Amounts in several currencies"]
    findings = [f["text"] for f in original.report_data["key_findings"]]
    assert not any(text.startswith("NON_LIFE: selected ultimate") for text in findings)
    portfolio = next(p for p in original.report_data["pages"] if p["module"] == "M02")["body"]
    lines = [r["line"] for r in portfolio["rows"]]
    assert "NON_LIFE · PROPERTY [EUR]" in lines and "NON_LIFE · PROPERTY [USD]" in lines
    business = [b["measure"] for b in portfolio["business"]]
    assert "PR04 Cancellation rate [TRY]" in business and "PR04 Cancellation rate [USD]" in business


@pytest.mark.slow
def test_the_original_view_cannot_restate_with_a_price_index(cache: Path, tmp_path: Path) -> None:
    from actuarycanary.pipeline import InputError
    from actuarycanary.structures.triangles import TriangleSettings

    settings = RunSettings(
        currency_view=ORIGINAL,
        triangles=TriangleSettings(value_basis=ValueBasis.INFLATION_ADJUSTED),
    )
    with pytest.raises(InputError, match="ORIGINAL currency view"):
        run(BASELINE, tmp_path, settings, cache_dir=cache)


@pytest.mark.slow
def test_the_option_of_the_command_line_reaches_the_run(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from actuarycanary.cli import app

    result = CliRunner().invoke(
        app,
        ["run", str(BASELINE), "--out", str(tmp_path), "--currency-view", "original"],
    )
    assert result.exit_code == 0, result.output
    manifest = next(tmp_path.glob("*/manifest.json")).read_text(encoding="utf-8")
    assert '"currency": "ORIGINAL"' in manifest
    wrong = CliRunner().invoke(app, ["run", str(BASELINE), "--currency-view", "functional"])
    assert wrong.exit_code != 0
