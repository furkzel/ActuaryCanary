"""Performance of the whole run (blueprint 14.3, decision 0081) and the bench that measures it.

The two-minute budget is for `large`, which takes minutes to write and to read; it is measured
by hand with `just bench data/synthetic/baseline/large` at each checkpoint. These tests keep the
same measurement honest on `medium`, with a budget a few times the time measured there, so a
slowdown of the kind that would break the budget on `large` shows here first.
"""

from pathlib import Path

import pytest

from actuarycanary.bench import IMPORT_STEP, Timing, format_report, time_run

ROOT = Path(__file__).parents[1]
MEDIUM = ROOT / "data" / "synthetic" / "baseline" / "medium"
BASELINE_TINY = Path(__file__).parent / "fixtures" / "synthetic" / "baseline"

# Seconds without the import. Measured on 2026-10-23, 16-core desktop: medium cold 15.3,
# warm 10.3. The budget leaves room for a busy machine (suite times doubled once at G2).
COLD_BUDGET = 45.0
WARM_BUDGET = 30.0
READING = "Reading and recognising spreadsheets"


def test_the_report_has_a_line_per_step_and_the_totals() -> None:
    cold = Timing(((IMPORT_STEP, 2.0), ("Reading", 5.0), ("Writing", 1.5)), 8.5)
    warm = Timing(((IMPORT_STEP, 0.0), ("Reading", 0.5), ("Writing", 1.5)), 2.0)
    lines = format_report(Path("some/folder"), cold, warm).splitlines()
    assert lines[0] == str(Path("some/folder"))
    assert lines[1].split() == ["step", "cold", "s", "warm", "s"]
    assert lines[3].split() == ["Reading", "5.0", "0.5"]
    assert lines[-1].split() == ["Total", "8.5", "2.0"]
    assert len(lines) == 2 + 3 + 1


@pytest.mark.slow
def test_a_run_announces_every_step_and_the_steps_add_up(tmp_path: Path) -> None:
    timing = time_run(BASELINE_TINY, tmp_path / "cache", tmp_path / "out")
    names = [name for name, _ in timing.steps]
    assert names[:2] == [IMPORT_STEP, READING] and names[-1] == "Writing the manifest"
    assert sum(seconds for _, seconds in timing.steps) == pytest.approx(timing.total)


@pytest.mark.slow
def test_medium_runs_inside_its_budget_cold_and_warm(tmp_path: Path) -> None:
    if not (MEDIUM / "claim_valuations.xlsx").exists():
        pytest.skip("run `just synth baseline medium` first")
    cache = tmp_path / "cache"
    cold = time_run(MEDIUM, cache, tmp_path / "cold")
    warm = time_run(MEDIUM, cache, tmp_path / "warm")
    report = format_report(MEDIUM, cold, warm)
    cold_s, warm_s = cold.total - cold.steps[0][1], warm.total - warm.steps[0][1]
    assert cold_s < COLD_BUDGET, report
    assert warm_s < WARM_BUDGET, report
    # the second run reads from the parquet cache, not from the spreadsheets again
    assert dict(warm.steps)[READING] < dict(cold.steps)[READING] / 2, report
