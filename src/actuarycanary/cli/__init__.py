"""Command line entry point (typer and rich)."""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from actuarycanary import __version__
from actuarycanary.manifest.metadata import load_metadata

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
