"""Times a run on a folder, cold and warm, and prints the time of each step (``just bench``).

Cold: the reader cache is empty, so every spreadsheet is read. Warm: the same cache is used
again. Both runs write their outputs into a temporary folder that is removed afterwards.
"""

import importlib
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

IMPORT_STEP = "Importing the package"
ENDED = "Total"


@dataclass(frozen=True)
class Timing:
    """Seconds per step, in the order the run announces them, and the total."""

    steps: tuple[tuple[str, float], ...]
    total: float
    lineage_bytes: tuple[tuple[str, int], ...] = ()  # size of each lineage file the run wrote


def time_run(
    folder: Path, cache_dir: Path, out_root: Path, lineage_format: int | None = None
) -> Timing:
    """One run of the whole pipeline on `folder` with the settings of ``canary run --yes``
    (no saved profiles, no questions); `lineage_format` None keeps the default."""
    started = time.perf_counter()
    pipeline = importlib.import_module("actuarycanary.pipeline")
    imported = time.perf_counter()
    marks: list[tuple[str, float]] = []

    def step(description: str) -> None:
        marks.append((description, time.perf_counter()))

    settings = (
        None if lineage_format is None else pipeline.RunSettings(lineage_format=lineage_format)
    )
    result = pipeline.run(folder, out_root, settings, cache_dir=cache_dir, progress=step)
    finished = time.perf_counter()
    lineage = tuple(
        (path.name, path.stat().st_size) for path in sorted(result.folder.glob("lineage*.csv"))
    )
    # the first step also holds loading the specifications, which comes before it is announced
    begins = [imported] + [at for _, at in marks[1:]]
    ends = begins[1:] + [finished]
    steps = [(IMPORT_STEP, imported - started)]
    steps += [
        (name, end - begin) for (name, _), begin, end in zip(marks, begins, ends, strict=True)
    ]
    return Timing(tuple(steps), finished - started, lineage)


def format_report(folder: Path, cold: Timing, warm: Timing) -> str:
    """Both timings as one text table, a line per step."""
    names = [name for name, _ in cold.steps]
    lookup = dict(warm.steps)
    width = max(len(n) for n in [*names, ENDED])
    lines = [f"{folder}", f"{'step':<{width}}  {'cold s':>8}  {'warm s':>8}"]
    for name, seconds in cold.steps:
        lines.append(f"{name:<{width}}  {seconds:>8.1f}  {lookup.get(name, 0.0):>8.1f}")
    lines.append(f"{ENDED:<{width}}  {cold.total:>8.1f}  {warm.total:>8.1f}")
    lines += [f"{name}: {size / 1e6:.1f} MB" for name, size in cold.lineage_bytes]
    return "\n".join(lines)


def main(
    folder: Annotated[Path, typer.Argument(help="Folder with claim_valuations.xlsx.")],
    lineage_format: Annotated[
        int | None, typer.Option("--lineage-format", help="1 or 2; default the run default.")
    ] = None,
) -> None:
    """Run the pipeline on FOLDER twice (cold, then warm) and print the time of each step."""
    with tempfile.TemporaryDirectory(prefix="canary-bench-") as work:
        root = Path(work)
        cold = time_run(folder, root / "cache", root / "cold", lineage_format)
        warm = time_run(folder, root / "cache", root / "warm", lineage_format)
    typer.echo(format_report(folder, cold, warm))


if __name__ == "__main__":
    typer.run(main)
