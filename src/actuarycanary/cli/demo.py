"""The example data `canary demo` runs on, found next to the program (also when frozen)."""

from pathlib import Path

EXAMPLES_FOLDER = "examples"
DEMO_FOLDERS = ("demo", "baseline")  # `demo` once it exists; until then the baseline example


def find_demo_folder(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the first examples/ folder holding the demo."""
    here = (start or Path(__file__)).resolve()
    for folder in (here, *here.parents):
        for name in DEMO_FOLDERS:
            candidate = folder / EXAMPLES_FOLDER / name
            if (candidate / "claim_valuations.xlsx").is_file():
                return candidate
    raise FileNotFoundError(f"{EXAMPLES_FOLDER}/demo not found above {here}")
