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


@pytest.fixture(scope="session")
def scenario_folder(tmp_path_factory: pytest.TempPathFactory):
    """Function `name -> folder` of a synthetic scenario written at size tiny by the generator
    as it is now (the committed fixtures are older). Written once per test session and shared by
    the workers: the first one to ask writes it, the others wait for it."""
    import time

    from actuarycanary.synthetic.build import synthesize

    base = tmp_path_factory.getbasetemp()
    shared = (base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base) / "scenarios"
    shared.mkdir(exist_ok=True)

    def folder(name: str) -> Path:
        out, done = shared / name, shared / f"{name}.done"
        try:
            out.mkdir()
        except FileExistsError:
            waited = 0.0
            while not done.exists():
                time.sleep(0.05)
                waited += 0.05
                assert waited < 120, f"scenario {name} was not written in time"
            return out
        synthesize(name, "tiny", out)
        done.touch()
        return out

    return folder


@pytest.fixture(scope="session")
def recognised_scenario(scenario_folder):
    """Function `name -> recognised sheets` of a tiny scenario (its folder and the subfolder of
    the later feeds), read once per worker."""
    from actuarycanary.pipeline import recognise_folder
    from actuarycanary.recognition.dictionary import build_dictionary
    from actuarycanary.spec.loader import load_specs

    dictionary = build_dictionary(load_specs())
    read: dict[str, list] = {}

    def recognised(name: str) -> list:
        if name not in read:
            folder = scenario_folder(name)
            later = folder / "phase2"  # the feeds the generator still writes apart (0242)
            read[name] = recognise_folder(folder, dictionary, None, None) + (
                recognise_folder(later, dictionary, None, None) if later.is_dir() else []
            )
        return read[name]

    return recognised
