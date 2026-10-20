from typer.testing import CliRunner

from actuarycanary import __version__
from actuarycanary.cli import app
from actuarycanary.manifest.metadata import load_metadata

runner = CliRunner()


def test_info_prints_project_name() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert load_metadata().name in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
