"""The `canary ui` command: start the local server, print the address, open the browser."""

import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from actuarycanary.ui.settings import DEFAULT_OUT, DEFAULT_PROFILES


def ui_command(
    out: Annotated[
        Path, typer.Option("--out", help="Output root folder the page starts with.")
    ] = Path(DEFAULT_OUT),
    profiles: Annotated[
        Path, typer.Option("--profiles", help="Folder of mapping profiles.")
    ] = Path(DEFAULT_PROFILES),
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the page in the browser.")
    ] = True,
    port: Annotated[
        int, typer.Option("--port", help="Port to listen on; 0 (default) picks a free one.")
    ] = 0,
    lang: Annotated[str, typer.Option("--lang", help="Language of the page: en or tr.")] = "en",
) -> None:
    """Start the local browser interface: choose a folder, see how the sheets were recognised,
    correct the mapping, run, and open the report. It listens on this computer only."""
    from actuarycanary.ui.server import UiServer
    from actuarycanary.ui.strings import LANGUAGES

    console = Console(width=100)
    if lang not in LANGUAGES:
        console.print(f"[red]Settings rejected:[/red] language {lang!r} is unknown; known: en, tr")
        raise typer.Exit(2)
    try:
        server = UiServer(port, str(out), str(profiles))
    except OSError as error:
        console.print(f"[red]Cannot start:[/red] {error}")
        raise typer.Exit(1) from error
    url = server.url(lang)
    console.print(f"canary ui is running at {url}", soft_wrap=True, highlight=False, markup=False)
    console.print("Press Ctrl+C or use the Quit button of the page to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("Stopped.")
    finally:
        server.server_close()
