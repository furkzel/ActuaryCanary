"""The example data `canary demo` runs on, found next to the program (also when frozen)."""

from pathlib import Path

EXAMPLES_FOLDER = "examples"
DEMO_FOLDER = "demo"
# the demo ships the generator's interest-rate workbook and names its curve, so that its report
# carries the discounted basis beside the nominal one (record 0346)
DEMO_CURVE = "TRY_GOV"


def find_demo_folder(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the first examples/demo folder with the data."""
    here = (start or Path(__file__)).resolve()
    for folder in (here, *here.parents):
        candidate = folder / EXAMPLES_FOLDER / DEMO_FOLDER
        if (candidate / "claim_valuations.xlsx").is_file():
            return candidate
    raise FileNotFoundError(f"{EXAMPLES_FOLDER}/{DEMO_FOLDER} not found above {here}")
