"""Command line entry point (typer and rich)."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from actuarycanary import __version__
from actuarycanary.canonical.feeds import CanonicalError
from actuarycanary.manifest.metadata import load_metadata
from actuarycanary.pipeline import InputError, RunResult, RunSettings, run
from actuarycanary.report import numbers
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleError, TriangleSettings

app = typer.Typer(help="Auditable, early-warning actuarial reporting.", no_args_is_help=True)


def _show_version(show: bool) -> None:
    if show:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Auditable, early-warning actuarial reporting."""


@app.command()
def info() -> None:
    """Print the project metadata."""
    metadata = load_metadata()
    table = Table(title=metadata.name)
    table.add_column("Field")
    table.add_column("Value", overflow="fold")
    rows = {
        "name": metadata.name,
        "version": metadata.version,
        "command": metadata.command,
        "tagline": metadata.tagline,
        "author": metadata.author,
        "contact": metadata.contact,
        "repository": metadata.repository,
        "licence": metadata.licence,
    }
    for field, value in rows.items():
        if value:  # empty metadata fields are left out on purpose
            table.add_row(field, value)
    Console(width=100).print(table)


def _summary(console: Console, result: RunResult) -> None:
    reserving = result.reserving
    currency = reserving.triangles.reporting_currency
    table = Table(title=f"Chain ladder, {currency}, cut-off {reserving.triangles.cut_off}")
    for column in ("Segment / line", "Paid", "Incurred", "Ultimate (incurred CL)", "IBNR"):
        table.add_column(column, justify="left" if column.startswith("Segment") else "right")
    for group in reserving.groups:
        totals = group.totals()
        table.add_row(
            " / ".join(group.group),
            numbers.amount(totals.paid),
            numbers.amount(totals.incurred),
            numbers.amount(totals.ultimate["incurred"]),
            numbers.amount(totals.ibnr("incurred")),
        )
    console.print(table)
    if result.findings:
        rows = sum(f.count for f in result.findings)
        console.print(f"{len(result.findings)} data rules touched {rows} rows; see the report.")
    console.print(f"Run id   {result.run_id}")
    console.print(f"Report   {result.report}", soft_wrap=True)
    console.print(f"Manifest {result.manifest}", soft_wrap=True)


@app.command("run")
def run_command(
    folder: Annotated[Path, typer.Argument(help="Folder with claim_valuations.xlsx.")],
    out: Annotated[Path, typer.Option("--out", help="Output root folder.")] = Path("out"),
    origin_period: Annotated[
        Period, typer.Option("--origin-period", case_sensitive=False)
    ] = Period.YEAR,
    development_period: Annotated[
        Period, typer.Option("--development-period", case_sensitive=False)
    ] = Period.YEAR,
) -> None:
    """Build paid and incurred triangles and chain ladder, then write report and manifest."""
    console = Console(width=100)
    try:
        settings = RunSettings(
            triangles=TriangleSettings(
                origin_period=origin_period, development_period=development_period
            )
        )
    except ValueError as error:
        console.print(f"[red]Settings rejected:[/red] {error}")
        raise typer.Exit(2) from error
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting", total=None)

        def step(description: str) -> None:
            progress.update(task, description=description)
            progress.console.print(f"  {description}")

        try:
            result = run(folder, out, settings, progress=step)
        except (InputError, CanonicalError, TriangleError) as error:
            console.print(f"[red]Cannot run:[/red] {error}")
            raise typer.Exit(1) from error
    _summary(console, result)
