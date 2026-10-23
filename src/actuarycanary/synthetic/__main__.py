"""Command line: ``python -m actuarycanary.synthetic write <scenario> <size>`` (``just synth``)."""

import shutil
import time
from pathlib import Path
from typing import Annotated

import typer

from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.build import synthesize
from actuarycanary.synthetic.scenario import list_scenarios

app = typer.Typer(add_completion=False, help="Synthetic input spreadsheets with ground truth.")

FIXTURE_SCENARIOS = ("baseline", "messy_headers")
FEED_FILES = ("claim_valuations", "claims", "policies", "premiums", "expenses", "market")


def _write(scenario: str, size: str, target: Path) -> None:
    started = time.perf_counter()
    manifest = synthesize(scenario, size, target)
    seconds = time.perf_counter() - started
    typer.echo(
        f"{scenario}/{size}: {manifest['claims_simulated']} claims -> {target} ({seconds:.1f} s)"
    )
    typer.echo(f"  rows: {manifest['rows']}")


@app.command()
def write(
    scenario: Annotated[str, typer.Argument(help="A file name in synthetic/scenarios/.")],
    size: Annotated[str, typer.Argument(help="tiny, medium or large.")] = "tiny",
    out: Annotated[
        Path | None, typer.Option(help="Folder; default data/synthetic/<scenario>/<size>.")
    ] = None,
) -> None:
    """Write one scenario at one size."""
    if scenario not in list_scenarios():
        raise typer.BadParameter(
            f"unknown scenario {scenario!r}; choose from {', '.join(list_scenarios())}"
        )
    _write(scenario, size, out or Path("data") / "synthetic" / scenario / size)


@app.command()
def fixtures() -> None:
    """Refresh the committed tiny versions: tests/fixtures/synthetic/ and examples/."""
    root = find_spec_root().parent
    for scenario in FIXTURE_SCENARIOS:
        target = root / "tests" / "fixtures" / "synthetic" / scenario
        shutil.rmtree(target, ignore_errors=True)
        _write(scenario, "tiny", target)
        example = root / "examples" / scenario
        shutil.rmtree(example, ignore_errors=True)
        example.mkdir(parents=True)
        for feed in FEED_FILES:
            shutil.copy(target / f"{feed}.xlsx", example / f"{feed}.xlsx")


if __name__ == "__main__":
    app()
