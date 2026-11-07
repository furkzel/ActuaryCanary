"""Refresh the examples (`just examples`).

Writes examples/demo from the scenario synthetic/scenarios/demo.yaml (the six input files and
the interest-rate workbook of the scenario, record 0346), then runs every folder of examples/ and
keeps its report and manifest in examples/<name>/report/. The demo runs as `canary demo` does,
with its curve named.
The tiny scenarios baseline and messy_headers are refreshed by `just synth-fixtures`, which
also copies their input files here.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from actuarycanary.cli.demo import DEMO_CURVE, DEMO_FOLDER
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.pipeline import RunSettings, run
from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.build import synthesize

FEED_FILES = ("claim_valuations", "claims", "policies", "premiums", "expenses", "market")
RATES_FILE = "interest_rates.xlsx"  # written by the generator under phase2/ (record 0242)
REPORT_FILES = ("report.html", "manifest.json")


def write_demo(examples: Path) -> None:
    """The fixed-seed demo scenario at its own size, the six spreadsheets only."""
    target = examples / "demo"
    with tempfile.TemporaryDirectory() as scratch:
        synthesize("demo", "demo", Path(scratch))
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        for feed in FEED_FILES:
            shutil.copy(Path(scratch) / f"{feed}.xlsx", target / f"{feed}.xlsx")
        shutil.copy(Path(scratch) / "phase2" / RATES_FILE, target / RATES_FILE)


def write_reports(examples: Path) -> None:
    """One run per example with the default settings; new layouts take the proposals (--yes)."""
    for folder in sorted(p for p in examples.iterdir() if p.is_dir()):
        with tempfile.TemporaryDirectory() as scratch:
            settings = (
                RunSettings(discount=DiscountSettings(curve_id=DEMO_CURVE))
                if folder.name == DEMO_FOLDER
                else RunSettings()
            )
            result = run(
                folder, Path(scratch) / "out", settings, profiles_dir=Path(scratch) / "profiles"
            )
            report = folder / "report"
            shutil.rmtree(report, ignore_errors=True)
            report.mkdir()
            for name in REPORT_FILES:
                shutil.copy(result.report.parent / name, report / name)
        print(f"{folder.name}: run id {result.run_id}")


def main() -> None:
    examples = find_spec_root().parent / "examples"
    if "--reports-only" not in sys.argv:
        write_demo(examples)
    write_reports(examples)


if __name__ == "__main__":
    main()
