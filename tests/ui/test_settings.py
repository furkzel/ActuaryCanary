"""The interface builds the settings of the command line, with its defaults."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from actuarycanary import cli
from actuarycanary.pipeline import RunSettings
from actuarycanary.ui import settings
from actuarycanary.ui.settings import Form, SettingsRejectedError, build_run_settings, command_line

CASES: list[tuple[list[str], dict[str, str]]] = [
    ([], {}),
    (["--lang", "tr"], {"lang": "tr"}),
    (["--basis", "net", "--currency", "usd"], {"basis": "net", "currency": "usd"}),
    (
        ["--value", "discounted", "--curve", "TRY_GOV", "--discount-date", "2025-06-30"],
        {"value": "discounted", "curve": "TRY_GOV", "discount_date": "2025-06-30"},
    ),
    (
        ["--value", "inflation-adjusted", "--value-date", "2025-12-31", "--price-index", "CPI_TR"],
        {"value": "inflation-adjusted", "value_date": "2025-12-31", "price_index": "CPI_TR"},
    ),
    (
        [
            "--origin-period", "year", "--development-period", "quarter",
            "--origin-axis", "report", "--currency-view", "original", "--lineage-format", "1",
        ],
        {
            "origin_period": "year", "development_period": "quarter", "origin_axis": "report",
            "currency_view": "original", "lineage_format": "1",
        },
    ),
]  # fmt: skip


@pytest.mark.parametrize(("options", "form"), CASES)
def test_the_form_builds_the_settings_the_command_line_builds(
    options: list[str], form: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[RunSettings] = []

    def capture(console: Any, folder: Path, out: Path, run_settings: RunSettings, *rest: Any):
        seen.append(run_settings)
        raise SystemExit(0)

    monkeypatch.setattr(cli, "_run_with_progress", capture)
    CliRunner().invoke(cli.app, ["run", str(tmp_path), *options])
    assert len(seen) == 1, "the command line did not reach the run"
    assert build_run_settings(Form(folder=str(tmp_path), values=form)) == seen[0]


def test_the_defaults_are_the_defaults_of_the_command_line() -> None:
    assert build_run_settings(Form()) == RunSettings()
    assert (settings.DEFAULT_OUT, settings.DEFAULT_PROFILES) == ("out", "profiles")


@pytest.mark.parametrize(
    "values",
    [
        {"lang": "de"},
        {"basis": "total"},
        {"value": "real"},
        {"lineage_format": "3"},
        {"lineage_format": "x"},
        {"value_date": "31.12.2025"},
        {"origin_period": "decade"},
        {"assumptions": "no/such/file.yaml"},
    ],
)
def test_choices_that_make_no_settings_are_rejected_with_a_message(values: dict[str, str]) -> None:
    with pytest.raises(SettingsRejectedError) as error:
        build_run_settings(Form(values=values))
    assert str(error.value)


def test_the_command_line_leaves_defaults_out_and_adds_what_differs() -> None:
    folder = Form(folder="data")
    assert command_line(folder, with_yes=False) == "canary run data"
    assert command_line(folder, with_yes=True) == "canary run data --yes"
    form = Form(
        folder="data",
        out="results",
        profiles="maps",
        values={"lang": "tr", "value": "discounted", "curve": "TRY_GOV", "currency": "usd"},
    )
    text = command_line(form, with_yes=False)
    assert text.split()[:3] == ["canary", "run", "data"]
    for part in ("--out results", "--lang tr", "--value discounted", "--curve TRY_GOV"):
        assert part in text
    assert "--currency USD" in text and "--profiles maps" in text


def test_a_folder_with_spaces_is_quoted() -> None:
    text = command_line(Form(folder=r"C:\My Data\claims"), with_yes=False)
    assert '"' in text or "'" in text
