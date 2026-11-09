"""The folder browser: drives and subfolders of the directories the person navigates to.

It lists names only and counts files by suffix; it never reads a file and never writes.
"""

import os
import string
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from actuarycanary.io.excel import SPREADSHEET_SUFFIXES

LIST_LIMIT = 500  # subfolders listed at most
COUNT_BUDGET_SECONDS = 1.5  # after this the subfolders are listed without counts
_SKIPPED = {"$recycle.bin", "system volume information"}


@dataclass(frozen=True)
class Counts:
    spreadsheets: int = 0  # .xlsx, .xlsm, .xls, .ods: what the program reads
    csv: int = 0  # counted only to say they are not read


def count_files(folder: Path) -> Counts | None:
    """Spreadsheets (lock files `~$` left out) and csv files directly in `folder`; None when
    the folder cannot be listed."""
    spreadsheets = csv = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                name = entry.name.lower()
                if name.startswith("~$") or not entry.is_file():
                    continue
                if name.endswith(SPREADSHEET_SUFFIXES):
                    spreadsheets += 1
                elif name.endswith(".csv"):
                    csv += 1
    except OSError:
        return None
    return Counts(spreadsheets, csv)


def drives() -> list[str]:
    """The roots to start from: drive letters on Windows, the root and the home folder elsewhere."""
    if sys.platform == "win32":
        return [
            f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")
        ]
    return sorted({"/", str(Path.home())})


def _counts_json(counts: Counts | None) -> dict[str, int] | None:
    return None if counts is None else {"spreadsheets": counts.spreadsheets, "csv": counts.csv}


def browse(path: str | None) -> dict[str, object]:
    """The folder `path` (the roots when empty): its parent, its counts and its subfolders.

    Raises FileNotFoundError when `path` is not a folder and PermissionError when it cannot be
    listed.
    """
    if not path:
        home = Path.home()
        return {
            "path": "",
            "parent": None,
            "roots": drives(),
            "home": str(home),
            "counts": None,
            "folders": [],
        }
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(path)
    folder = folder.resolve()
    try:
        names = sorted(
            (e.name for e in os.scandir(folder) if e.is_dir() and not e.name.startswith(".")),
            key=str.lower,
        )
    except PermissionError:
        raise
    names = [n for n in names if n.lower() not in _SKIPPED]
    started = time.monotonic()
    folders: list[dict[str, object]] = []
    for name in names[:LIST_LIMIT]:
        child = folder / name
        counted = time.monotonic() - started < COUNT_BUDGET_SECONDS
        folders.append(
            {
                "name": name,
                "path": str(child),
                "counts": _counts_json(count_files(child)) if counted else None,
            }
        )
    parent = folder.parent
    return {
        "path": str(folder),
        "parent": None if parent == folder else str(parent),
        "roots": drives(),
        "home": str(Path.home()),
        "counts": _counts_json(count_files(folder)),
        "folders": folders,
        "more": max(0, len(names) - LIST_LIMIT),
    }
