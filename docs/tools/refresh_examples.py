"""Refresh the examples (`just examples`).

Refreshes the tiny fixtures of baseline and messy_headers (the work of `just synth-fixtures`),
writes examples/demo from the scenario synthetic/scenarios/demo.yaml, copies every spreadsheet
the generator writes into the scenario folder (the six feeds, the reinsurance treaties and
transactions, the recoveries and the ledger, with their `_partN` workbooks) and, for the demo,
the interest-rate workbook of `phase2/` (records 0346, 0382, 0811). Truth files, canonical
copies and the other `phase2/` workbooks stay where they are: they are not examples. Then it runs
every folder of examples/ and keeps its report and manifest in examples/<name>/report/. The demo
runs as `canary demo` does, with its curve named; its ledger account-mapping profile is saved
confirmed on the generation date before the committed run (record 0811).
"""

import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from actuarycanary.cli.demo import DEMO_CURVE, DEMO_FOLDER
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.ledger.profile import PREFIX, SUFFIX, read_profile, save_profile
from actuarycanary.pipeline import RunSettings, run
from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.__main__ import FIXTURE_SCENARIOS, fixtures
from actuarycanary.synthetic.build import synthesize

RATES_FILE = "interest_rates.xlsx"  # written by the generator under phase2/ (record 0242)
REPORT_FILES = ("report.html", "manifest.json")


def copy_feeds(source: Path, target: Path, rates: bool = False) -> list[str]:
    """Copy every spreadsheet of the scenario folder `source` (not its subfolders) into `target`;
    with `rates` also the interest-rate workbook of `source/phase2`. Returns the names."""
    target.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in source.glob("*.xlsx"))
    for name in names:
        shutil.copy(source / name, target / name)
    if rates:
        shutil.copy(source / "phase2" / RATES_FILE, target / RATES_FILE)
        names.append(RATES_FILE)
    return names


def write_demo(examples: Path) -> None:
    """The fixed-seed demo scenario at its own size, every feed of the generator."""
    target = examples / "demo"
    with tempfile.TemporaryDirectory() as scratch:
        synthesize("demo", "demo", Path(scratch))
        shutil.rmtree(target, ignore_errors=True)
        copy_feeds(Path(scratch), target, rates=True)


def write_tiny(root: Path) -> None:
    """The tiny fixtures and the examples that carry their feeds."""
    fixtures()
    for scenario in FIXTURE_SCENARIOS:
        target = root / "examples" / scenario
        shutil.rmtree(target, ignore_errors=True)
        copy_feeds(root / "tests" / "fixtures" / "synthetic" / scenario, target)


def confirm_ledger_profiles(profiles: Path, on: date) -> list[Path]:
    """Mark every saved ledger account-mapping profile in `profiles` as confirmed on `on`."""
    saved = []
    for path in sorted(profiles.glob(f"{PREFIX}*{SUFFIX}")):
        profile, _ = read_profile(path)
        saved.append(save_profile(profiles, profile.model_copy(update={"confirmed_on": on})))
    return saved


def write_reports(examples: Path) -> None:
    """One run per example with the default settings; new layouts take the proposals (--yes)."""
    for folder in sorted(p for p in examples.iterdir() if p.is_dir()):
        with tempfile.TemporaryDirectory() as scratch:
            settings = (
                RunSettings(discount=DiscountSettings(curve_id=DEMO_CURVE))
                if folder.name == DEMO_FOLDER
                else RunSettings()
            )
            profiles = Path(scratch) / "profiles"
            result = run(folder, Path(scratch) / "out", settings, profiles_dir=profiles)
            shipped: list[Path] = []
            if folder.name == DEMO_FOLDER and (
                shipped := confirm_ledger_profiles(profiles, date.today())
            ):
                # the shipped demo reads "confirmed", not "proposed" (record 0811)
                result = run(folder, Path(scratch) / "again", settings, profiles_dir=profiles)
            report = folder / "report"
            shutil.rmtree(report, ignore_errors=True)
            report.mkdir()
            for name in REPORT_FILES:
                shutil.copy(result.report.parent / name, report / name)
            for path in shipped:  # the confirmed profile the committed run used
                shutil.copy(path, report / path.name)
        print(f"{folder.name}: run id {result.run_id}")


def main() -> None:
    examples = find_spec_root().parent / "examples"
    if "--reports-only" not in sys.argv:
        write_tiny(examples.parent)
        write_demo(examples)
    write_reports(examples)


if __name__ == "__main__":
    main()
