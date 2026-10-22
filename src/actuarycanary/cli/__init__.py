"""Command line entry point (typer and rich)."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from actuarycanary import __version__
from actuarycanary.canonical.feeds import CanonicalError
from actuarycanary.cli.confirm import confirm_tables
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import ConversionError
from actuarycanary.io.excel import RawTable
from actuarycanary.manifest.metadata import load_metadata
from actuarycanary.pipeline import InputError, RunResult, RunSettings, run
from actuarycanary.quality.output import print_summary
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.mapping_profiles import ProfileError
from actuarycanary.recognition.tables import TableRecognition
from actuarycanary.report import numbers
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import OriginAxis, TriangleError, TriangleSettings


class BasisOption(StrEnum):
    GROSS = "gross"
    CEDED = "ceded"
    NET = "net"


class ValueOption(StrEnum):
    NOMINAL = "nominal"
    INFLATION_ADJUSTED = "inflation-adjusted"


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


def _tables(console: Console, result: RunResult) -> None:
    table = Table(title="Sheets read", title_justify="left")
    for column in ("File [sheet]", "Concept", "Mapping", "Personal data dropped"):
        table.add_column(column, overflow="fold")
    for rec in result.tables:
        dropped = ", ".join(m.source.strip() for m in rec.personal)
        table.add_row(escape(rec.label), rec.concept or "-", str(rec.source), escape(dropped))
    console.print(table)


def _summary(console: Console, result: RunResult) -> None:
    _tables(console, result)
    print_summary(console, result.quality)
    reserving = result.reserving
    currency = reserving.triangles.reporting_currency
    settings = reserving.triangles.settings
    basis = f"{settings.reinsurance_basis.value}, {settings.value_basis.value}"
    table = Table(title=f"Chain ladder, {currency}, {basis}, cut-off {reserving.triangles.cut_off}")
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
    origin_axis: Annotated[
        OriginAxis,
        typer.Option(
            "--origin-axis",
            case_sensitive=False,
            help="Origin of a claim: accident, report, underwriting or first_valuation.",
        ),
    ] = OriginAxis.ACCIDENT,
    basis: Annotated[
        BasisOption,
        typer.Option(
            "--basis", case_sensitive=False, help="Reinsurance basis: gross, ceded or net."
        ),
    ] = BasisOption.GROSS,
    currency: Annotated[
        str | None,
        typer.Option(
            "--currency",
            help="Reporting currency; converts other currencies with the market data (CV01).",
        ),
    ] = None,
    value: Annotated[
        ValueOption,
        typer.Option(
            "--value",
            case_sensitive=False,
            help="Value basis: nominal or inflation-adjusted to the value date (CV02).",
        ),
    ] = ValueOption.NOMINAL,
    value_date: Annotated[
        str | None,
        typer.Option("--value-date", help="Prices of this date, YYYY-MM-DD; default the cut-off."),
    ] = None,
    price_index: Annotated[
        str | None,
        typer.Option("--price-index", help="Price index series_id; default from project.yaml."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Do not ask: use saved mapping profiles and, for new layouts, the proposals "
            "(not saved).",
        ),
    ] = False,
    profiles: Annotated[
        Path, typer.Option("--profiles", help="Folder of mapping profiles.")
    ] = Path("profiles"),
) -> None:
    """Recognise the spreadsheets in a folder, build paid and incurred triangles and chain
    ladder, then write report and manifest."""
    console = Console(width=100)
    try:
        settings = RunSettings(
            reporting_currency=currency.upper() if currency else None,
            use_market=currency is not None,
            triangles=TriangleSettings(
                origin_period=origin_period,
                development_period=development_period,
                origin_axis=origin_axis,
                reinsurance_basis=ReinsuranceBasis(basis.value.upper()),
                value_basis=ValueBasis(value.value.upper().replace("-", "_")),
                value_date=date.fromisoformat(value_date) if value_date else None,
                price_index=price_index,
            ),
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

        def confirm(
            pending: list[tuple[TableRecognition, RawTable]], dictionary: Dictionary
        ) -> list[TableRecognition]:
            progress.stop()
            try:
                return confirm_tables(console, pending, dictionary)
            finally:
                progress.start()

        try:
            result = run(
                folder,
                out,
                settings,
                progress=step,
                profiles_dir=profiles,
                confirm=None if yes else confirm,
            )
        except (
            InputError,
            CanonicalError,
            TriangleError,
            ConversionError,
            ProfileError,
        ) as error:
            console.print(f"[red]Cannot run:[/red] {escape(str(error))}")
            raise typer.Exit(1) from error
        except EOFError as error:
            console.print(
                "[red]Cannot run:[/red] new layouts need confirming on the terminal; "
                "rerun with --yes to use the proposals without saving them."
            )
            raise typer.Exit(1) from error
    _summary(console, result)
