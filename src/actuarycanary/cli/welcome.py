"""What the program says when started without a command, and the Windows double-click case."""

import sys
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from actuarycanary.manifest.metadata import load_metadata


def console_is_only_ours() -> bool:
    """True on Windows when no other process shares this console (started by double-click).

    A program started from PowerShell or cmd shares its console with the shell, so the count
    of processes on the console is two or more; a double-click gives the program a console of
    its own that closes when it exits.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    slots = (ctypes.c_uint * 4)()
    count = ctypes.windll.kernel32.GetConsoleProcessList(slots, len(slots))  # type: ignore[attr-defined]
    return count == 1


def wait_for_key() -> None:
    """Block until a key is pressed (Windows console); returns at once elsewhere."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.getch()


def welcome_lines() -> list[str]:
    metadata = load_metadata()
    return [
        f"{metadata.name} {metadata.version}",
        metadata.tagline,
        "",
        "Two commands to try:",
        "  canary demo            run on the example data and open the report",
        "  canary run <folder>    run on your own spreadsheets",
        "",
        "Open PowerShell in this folder and type one of them.",
        "(In Explorer: click the address bar, type powershell, press Enter.)",
    ]


def show_welcome(
    console: Console,
    owns_console: Callable[[], bool] = console_is_only_ours,
    wait: Callable[[], None] = wait_for_key,
    interactive: bool | None = None,
) -> None:
    """Print the welcome text; if the console is ours alone, wait for a key before it closes."""
    for line in welcome_lines():
        console.print(line, highlight=False, markup=False)
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    if interactive and owns_console():
        console.print("\nPress any key to close this window.", highlight=False)
        wait()


def demo_closing_lines(report: Path, run_folder: Path) -> list[str]:
    """Where the results are and how to go on, in lines of at most 80 columns."""
    return [
        "",
        "Done. The report page and the run folder:",
        f"  {report}",
        f"  {run_folder}",
        "",
        "To run on your own files, put them in one folder and type:",
        "  canary run <folder>",
    ]
