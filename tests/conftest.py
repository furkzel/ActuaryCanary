import os
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from typer.testing import CliRunner

settings.register_profile("dev", max_examples=25, deadline=None)
settings.register_profile(
    "ci", max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


BASELINE_TINY = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"


@pytest.fixture(scope="session")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A spreadsheet cache of its own, so that tests do not write into the project."""
    return tmp_path_factory.mktemp("cache")


@pytest.fixture(scope="session")
def default_run(tmp_path_factory: pytest.TempPathFactory, cache: Path):
    """The default run of the tiny baseline, made once per worker and read by every fast test
    that needs a full run. A test that needs another run is marked `slow`."""
    from actuarycanary.pipeline import run

    return run(BASELINE_TINY, tmp_path_factory.mktemp("default"), cache_dir=cache)


@pytest.fixture(scope="session")
def cli_run(tmp_path_factory: pytest.TempPathFactory):
    """The same run through the command line: (folder of the run, terminal output)."""
    from actuarycanary.cli import app

    out = tmp_path_factory.mktemp("cli")
    result = CliRunner().invoke(app, ["run", str(BASELINE_TINY), "--out", str(out)])
    assert result.exit_code == 0, result.output
    return next(out.iterdir()), result.output
