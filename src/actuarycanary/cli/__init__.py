"""Command line entry point (typer and rich)."""

import sys
import textwrap
import webbrowser
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
from actuarycanary.cli.demo import find_demo_folder
from actuarycanary.cli.welcome import demo_closing_lines, show_welcome
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import ConversionError
from actuarycanary.io.excel import RawTable
from actuarycanary.manifest.metadata import load_metadata
from actuarycanary.measures.lineage import DEFAULT_FORMAT as DEFAULT_LINEAGE_FORMAT
from actuarycanary.methods.assumptions import AssumptionError, AssumptionsRegister
from actuarycanary.modules.runner import ModuleState
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


class LanguageOption(StrEnum):
    EN = "en"
    TR = "tr"


class CurrencyViewOption(StrEnum):
    REPORTING = "reporting"
    ORIGINAL = "original"


class ValueOption(StrEnum):
    NOMINAL = "nominal"
    INFLATION_ADJUSTED = "inflation-adjusted"


app = typer.Typer(help="Auditable, early-warning actuarial reporting.")


def _show_version(show: bool) -> None:
    if show:
        typer.echo(__version__)
        raise typer.Exit()


def use_utf8_streams() -> None:
    """Write UTF-8 to the console and to redirected output whatever the code page (Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Auditable, early-warning actuarial reporting."""
    use_utf8_streams()
    if ctx.invoked_subcommand is None:
        show_welcome(Console(width=80))


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


def _modules(console: Console, result: RunResult) -> None:
    table = Table(title="Modules", title_justify="left")
    for column in ("Module", "State", "Why"):
        table.add_column(column, overflow="fold")
    for outcome in result.analysis.modules:
        table.add_row(
            escape(f"{outcome.module} {outcome.title}"),
            outcome.state.value,
            escape("; ".join(outcome.reasons)),
            style="red" if outcome.state is ModuleState.SKIPPED else None,
        )
    console.print(table)


SUMMARY_WIDTH = 78  # the new summary lines wrap here so they fit an 80-column window


def _diagnostics(console: Console, result: RunResult) -> None:
    """One line: the method diagnostics per line of business, wrapped for 80 columns."""
    counts = result.reserving.diagnostics_by_group()
    if not counts:
        return
    total = sum(counts.values())
    per_line = ", ".join(f"{group[1]} {count}" for group, count in counts.items())
    line = f"Method diagnostics: {total} ({per_line}); see the report."
    for part in textwrap.wrap(line, SUMMARY_WIDTH, subsequent_indent="  "):
        console.print(escape(part), soft_wrap=True)


def _summary(console: Console, result: RunResult) -> None:
    _tables(console, result)
    print_summary(console, result.quality)
    _modules(console, result)
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
    _diagnostics(console, result)
    if result.findings:
        rows = sum(f.count for f in result.findings)
        console.print(f"{len(result.findings)} data rules touched {rows} rows; see the report.")
    console.print(f"Run id   {result.run_id}")
    console.print(f"Report   {result.report}", soft_wrap=True)
    console.print(f"Manifest {result.manifest}", soft_wrap=True)


def _run_with_progress(
    console: Console, folder: Path, out: Path, settings: RunSettings, yes: bool, profiles: Path
) -> RunResult:
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
            return run(
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
            AssumptionError,
        ) as error:
            console.print(f"[red]Cannot run:[/red] {escape(str(error))}")
            raise typer.Exit(1) from error
        except EOFError as error:
            console.print(
                "[red]Cannot run:[/red] new layouts need confirming on the terminal; "
                "rerun with --yes to use the proposals without saving them."
            )
            raise typer.Exit(1) from error


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
            help="Reporting currency; other currencies are converted with the market data (CV01).",
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
    currency_view: Annotated[
        CurrencyViewOption,
        typer.Option(
            "--currency-view",
            case_sensitive=False,
            help="reporting (default): everything in one currency (CV01); original: nothing "
            "converted, each line kept apart per currency. FUNCTIONAL equals reporting.",
        ),
    ] = CurrencyViewOption.REPORTING,
    lang: Annotated[
        LanguageOption,
        typer.Option(
            "--lang",
            case_sensitive=False,
            help="Language of report.html: en (default) or tr. The terminal stays English.",
        ),
    ] = LanguageOption.EN,
    lineage_format: Annotated[
        int,
        typer.Option(
            "--lineage-format",
            help="1: lineage.csv with row ranges per value; 2 (default): rows listed once in "
            "lineage_atoms.csv, much smaller on large inputs.",
        ),
    ] = DEFAULT_LINEAGE_FORMAT,
    assumptions: Annotated[
        Path | None,
        typer.Option(
            "--assumptions",
            help="YAML file with the assumptions register: selected factors, exclusions, "
            "priors, future inflation, overrides (every entry needs who and why).",
        ),
    ] = None,
) -> None:
    """Recognise the spreadsheets in a folder, build paid and incurred triangles and chain
    ladder, then write report and manifest."""
    console = Console(width=100)
    try:
        settings = RunSettings(
            reporting_currency=currency.upper() if currency else None,
            lineage_format=lineage_format,
            language=lang.value,
            currency_view=currency_view.value.upper(),
            triangles=TriangleSettings(
                origin_period=origin_period,
                development_period=development_period,
                origin_axis=origin_axis,
                reinsurance_basis=ReinsuranceBasis(basis.value.upper()),
                value_basis=ValueBasis(value.value.upper().replace("-", "_")),
                value_date=date.fromisoformat(value_date) if value_date else None,
                price_index=price_index,
            ),
            assumptions=(
                AssumptionsRegister.from_yaml(assumptions) if assumptions else AssumptionsRegister()
            ),
        )
    except (ValueError, OSError) as error:
        console.print(f"[red]Settings rejected:[/red] {error}")
        raise typer.Exit(2) from error
    result = _run_with_progress(console, folder, out, settings, yes, profiles)
    _summary(console, result)


@app.command("demo")
def demo_command(
    out: Annotated[Path, typer.Option("--out", help="Output root folder.")] = Path("out"),
    open_report: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the report in the browser.")
    ] = True,
) -> None:
    """Run on the example data that ships with the program and open the report."""
    console = Console(width=100)
    try:
        folder = find_demo_folder()
    except FileNotFoundError as error:
        console.print(f"[red]Cannot run:[/red] {escape(str(error))}")
        raise typer.Exit(1) from error
    console.print(f"Example data {folder}", soft_wrap=True)
    result = _run_with_progress(console, folder, out, RunSettings(), True, Path("profiles"))
    _summary(console, result)
    for line in demo_closing_lines(result.report.resolve(), result.report.resolve().parent):
        console.print(line, highlight=False, markup=False, soft_wrap=True)
    if open_report:
        webbrowser.open(result.report.resolve().as_uri())
