import io
import sys

import pytest
from rich.console import Console
from typer.testing import CliRunner

import actuarycanary.cli as cli
from actuarycanary.cli import welcome
from actuarycanary.cli.welcome import demo_closing_lines, show_welcome, welcome_lines

runner = CliRunner()


def _show(owns: bool, interactive: bool) -> tuple[str, list[str]]:
    waited: list[str] = []
    buffer = io.StringIO()
    console = Console(file=buffer, width=80)
    show_welcome(
        console,
        owns_console=lambda: owns,
        wait=lambda: waited.append("key"),
        interactive=interactive,
    )
    return buffer.getvalue(), waited


def test_the_welcome_names_the_program_and_the_two_commands() -> None:
    text = "\n".join(welcome_lines())
    assert "ActuaryCanary" in text
    assert "canary demo" in text
    assert "canary run <folder>" in text
    assert "PowerShell" in text


def test_it_waits_for_a_key_when_the_console_is_ours_alone() -> None:
    output, waited = _show(owns=True, interactive=True)
    assert waited == ["key"]
    assert "Press any key" in output


def test_it_exits_at_once_from_an_existing_terminal() -> None:
    output, waited = _show(owns=False, interactive=True)
    assert waited == []
    assert "Press any key" not in output
    assert "canary demo" in output


def test_it_never_waits_when_input_is_not_a_console() -> None:
    _, waited = _show(owns=True, interactive=False)
    assert waited == []


def test_console_detection_is_false_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(welcome.sys, "platform", "linux")
    assert welcome.console_is_only_ours() is False


def test_no_arguments_print_the_welcome_and_exit_zero() -> None:
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0
    assert "canary demo" in result.output
    assert "Usage:" not in result.output


def test_help_is_still_available() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_the_demo_closing_lines_fit_80_columns_and_name_both_places(tmp_path) -> None:
    report = tmp_path / "abc" / "report.html"
    lines = demo_closing_lines(report, report.parent)
    assert str(report) in lines[2] + lines[3] and str(report.parent) in lines[3]
    assert "canary run <folder>" in "\n".join(lines)
    assert all(len(line) <= 80 for line in lines if str(tmp_path) not in line)


def test_waiting_for_a_key_returns_at_once_where_the_windows_console_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(welcome.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "msvcrt", None)  # an import would now fail
    welcome.wait_for_key()


def test_the_welcome_without_a_command_runs_where_the_windows_console_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(welcome.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "msvcrt", None)
    buffer = io.StringIO()
    show_welcome(Console(file=buffer, width=80), interactive=True)
    assert "canary demo" in buffer.getvalue()
    assert "Press any key" not in buffer.getvalue()
    assert runner.invoke(cli.app, []).exit_code == 0
