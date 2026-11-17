"""Refresh the examples (`just examples`).

Writes examples/demo from the scenario synthetic/scenarios/demo.yaml, copies every spreadsheet
of the scenario folder (the six feeds, the reinsurance treaties and transactions, the recoveries
and the ledger, with their `_partN` workbooks; baseline and messy_headers: those of the committed
tiny fixtures, which hold the six feeds) and, for the demo,
the interest-rate workbook of `phase2/` (records 0346, 0382, 0811). Truth files, canonical
copies and the other `phase2/` workbooks stay where they are: they are not examples. Then it runs
every folder of examples/ and keeps its report and manifest in examples/<name>/report/. The demo
runs as `canary demo` does, with its curve named. Its ledger account-mapping profile is saved
confirmed on the generation date when the demo ships none yet (record 0811); a profile that is
shipped is copied unchanged, so that a refresh of the reports keeps the run id (record 0816).
"""

import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from actuarycanary.cli.demo import DEMO_CURVE, DEMO_FOLDER, place_demo_profiles
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.ledger.profile import PREFIX, SUFFIX, read_profile, save_profile
from actuarycanary.pipeline import RunSettings, run
from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.__main__ import FIXTURE_SCENARIOS
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
    """The examples that carry the feeds of the committed tiny fixtures. The fixtures are not
    regenerated here: tests and the golden copy read them as the ledger-free tiny set (record
    0811); `just synth-fixtures` refreshes them, with the tests that depend on them."""
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


def run_example(folder: Path, scratch: Path, today: date) -> tuple[Any, list[Path]]:
    """One run of an example with the default settings (the demo with its curve, as `canary demo`
    runs it); new layouts take the proposals (--yes). The ledger account-mapping profile the
    example ships beside its report is copied into the run's profiles folder unchanged, and the
    run reads it as it is (record 0816). Only an example that ships none gets one: the profile
    the first run proposed is confirmed on `today` and the example runs again, so that it reads
    "confirmed", not "proposed" (record 0811). Returns the result and the profile files used."""
    settings = (
        RunSettings(discount=DiscountSettings(curve_id=DEMO_CURVE))
        if folder.name == DEMO_FOLDER
        else RunSettings()
    )
    profiles = scratch / "profiles"
    placed = place_demo_profiles(folder, profiles)
    result = run(folder, scratch / "out", settings, profiles_dir=profiles)
    if placed:
        return result, placed
    shipped = confirm_ledger_profiles(profiles, today)
    if shipped:
        result = run(folder, scratch / "again", settings, profiles_dir=profiles)
    return result, shipped


def write_reports(examples: Path, today: date | None = None) -> dict[str, str]:
    """The report and manifest of every example, with the profile it ships; returns the run ids."""
    ids: dict[str, str] = {}
    for folder in sorted(p for p in examples.iterdir() if p.is_dir()):
        with tempfile.TemporaryDirectory() as scratch:
            result, shipped = run_example(folder, Path(scratch), today or date.today())
            report = folder / "report"
            kept = {path.name: path.read_bytes() for path in shipped}  # read before the wipe
            shutil.rmtree(report, ignore_errors=True)
            report.mkdir()
            for name in REPORT_FILES:
                shutil.copy(result.report.parent / name, report / name)
            for name, content in kept.items():  # the confirmed profile the committed run used
                (report / name).write_bytes(content)
        ids[folder.name] = result.run_id
        print(f"{folder.name}: run id {result.run_id}")
    return ids


def main() -> None:
    examples = find_spec_root().parent / "examples"
    if "--reports-only" not in sys.argv:
        write_tiny(examples.parent)
        write_demo(examples)
    write_reports(examples)


if __name__ == "__main__":
    main()
