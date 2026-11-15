"""The example data `canary demo` runs on, found next to the program (also when frozen)."""

import shutil
from pathlib import Path

from actuarycanary.ledger.profile import PREFIX, SUFFIX

EXAMPLES_FOLDER = "examples"
DEMO_FOLDER = "demo"
# the demo ships the generator's interest-rate workbook and names its curve, so that its report
# carries the discounted basis beside the nominal one (record 0346)
DEMO_CURVE = "TRY_GOV"
# the confirmed account-mapping profile of the demo's ledger lies beside its committed report
# (record 0811); the demo runs with it, so that it gives the run id of that report (record 0812)
DEMO_PROFILES = "report"


def find_demo_folder(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the first examples/demo folder with the data."""
    here = (start or Path(__file__)).resolve()
    for folder in (here, *here.parents):
        candidate = folder / EXAMPLES_FOLDER / DEMO_FOLDER
        if (candidate / "claim_valuations.xlsx").is_file():
            return candidate
    raise FileNotFoundError(f"{EXAMPLES_FOLDER}/{DEMO_FOLDER} not found above {here}")


def place_demo_profiles(folder: Path, profiles: Path) -> list[Path]:
    """Copy the ledger account-mapping profiles shipped with the demo `folder` into `profiles`,
    byte for byte, and return the copies. A file already there is the person's and is kept; a
    demo without shipped profiles (none beside the data) copies nothing and runs on a proposal."""
    placed: list[Path] = []
    for source in sorted((folder / DEMO_PROFILES).glob(f"{PREFIX}*{SUFFIX}")):
        target = profiles / source.name
        if not target.exists():
            profiles.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            placed.append(target)
    return placed
