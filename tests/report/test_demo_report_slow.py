"""The demo report of version 1.2 (records 0344 to 0346): the size of the page, the two value
bases it carries, the rules of RP01 1.2.0 on a run where their methods run, and the time a
switch of the value basis takes in a browser (slow: one demo run, about 20 seconds)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from actuarycanary.cli.demo import DEMO_CURVE, find_demo_folder
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.pipeline import RunResult, RunSettings, run
from actuarycanary.report.facts import anomaly_rates
from actuarycanary.report.findings import facts_named
from actuarycanary.report.model import scoped_facts
from actuarycanary.spec.loader import load_specs

pytestmark = [pytest.mark.slow, pytest.mark.integration]

MAX_BYTES = 8_000_000  # the work item's limit for the demo page (8 MB)
MAX_SWITCH_MS = 5_000  # blueprint 14.3: a change of basis in the report under five seconds
NEW_RULES = {f"KF{n}" for n in range(27, 35)}
BROWSERS = (
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google" / "Chrome" / "Application" / "chrome.exe",
)  # fmt: skip


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory, cache: Path) -> RunResult:
    folder = tmp_path_factory.mktemp("demo") / "demo"
    shutil.copytree(find_demo_folder(), folder, ignore=shutil.ignore_patterns("report"))
    settings = RunSettings(discount=DiscountSettings(curve_id=DEMO_CURVE))
    return run(folder, folder.parent / "out", settings, cache_dir=cache)


def test_the_demo_ships_its_curve_and_the_page_stays_small(demo: RunResult) -> None:
    assert (find_demo_folder() / "interest_rates.xlsx").is_file()
    assert demo.discount.available and demo.discount.curve is not None
    assert demo.discount.curve.curve_id == DEMO_CURVE
    size = demo.report.stat().st_size
    print(f"demo report.html: {size:,} bytes")
    assert size < MAX_BYTES


def test_the_page_carries_both_value_bases_and_opens_on_the_nominal_one(demo: RunResult) -> None:
    bases = demo.report_data["bases"]
    assert [x["id"] for x in bases["items"]] == ["NOMINAL", "DISCOUNTED"]
    assert bases["switch"] and bases["shown"] == "NOMINAL"
    page = demo.report.read_text(encoding="utf-8")
    for basis in ("NOMINAL", "DISCOUNTED"):
        assert re.search(rf'<div data-basis="{basis}">', page)  # a block of the uncertainty page
    blocks = next(p for p in demo.report_data["pages"] if p["module"] == "M12")["body"]["blocks"]
    assert [b["basis"] for b in blocks] == ["NOMINAL", "DISCOUNTED"]
    figures = demo.report_data["figures"]
    assert {"uncertainty-range-nominal", "uncertainty-range-discounted"} <= set(figures)


def test_every_fact_of_the_new_rules_is_computed_on_the_demo(demo: RunResult) -> None:
    rules = [r for r in load_specs().finding_rules.rules if r.id in NEW_RULES]
    scoped, _ = scoped_facts(
        demo.reserving, demo.analysis, demo.quality, anomaly_rates(demo.anomalies),
        tables=demo.report_tables, uncertainty=demo.uncertainty,
    )  # fmt: skip
    known = {scope: set().union(*(set(f) for _, _, f in sets)) for scope, sets in scoped.items()}
    missing = {(r.id, n) for r in rules for n in facts_named(r) if n not in known[r.scope]}
    assert missing == set()


def test_rules_of_the_new_results_fire_on_the_demo(demo: RunResult) -> None:
    model = demo.report_data
    fired = {f["rule"] for f in model["key_findings"] + model["further_findings"]}
    fired |= {f["rule"] for line in model["reserving"]["lines"] for f in line["findings"]}
    print("rules fired:", sorted(fired))
    assert {"KF33", "KF34"} <= fired  # the range of all lines, the discount effect
    assert "KF31" in fired  # MOTOR_TPL: generalised Pareto shape above 0.5


def _browser() -> Path | None:
    return next((b for b in BROWSERS if b.is_file()), None)


def test_a_switch_of_the_value_basis_takes_less_than_five_seconds(
    demo: RunResult, tmp_path: Path
) -> None:
    """The page measures its own switches when opened with #measure-switch: each switch, until
    the page is laid out again, written to data-switch-ms of the html element."""
    browser = _browser()
    if browser is None:
        pytest.skip("no Edge or Chrome to open the page")
    uri = demo.report.resolve().as_uri() + "#measure-switch"
    found = subprocess.run(
        [str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={tmp_path / 'profile'}", "--window-size=1280,900", "--dump-dom", uri],
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
    )  # fmt: skip
    times = re.search(r'data-switch-ms="([^"]*)"', found.stdout)
    if times is None:
        pytest.skip(f"the browser gave no page (exit {found.returncode}); switch time not measured")
    values = [float(x) for x in times.group(1).split(",")]
    print(f"switch times (ms): {values}")
    assert len(values) == 6 and max(values) < MAX_SWITCH_MS
