"""M08 in a run of the tiny reinsurance_heavy scenario: the module runs, writes its files and
the reconciliation finds the treaty years the data move (injected faults, the other clause).

Spec IDs proved: M08.
"""

import shutil
from pathlib import Path

import polars as pl
import pytest

from actuarycanary.pipeline import run


@pytest.mark.slow
def test_m08_runs_on_the_heavy_programme(tmp_path: Path, scenario_folder, cache: Path) -> None:
    source = scenario_folder("reinsurance_heavy")
    folder = tmp_path / "in"
    folder.mkdir()
    for book in [*source.glob("*.xlsx"), *(source / "phase2").glob("*.xlsx")]:
        shutil.copyfile(book, folder / book.name)
    result = run(folder, tmp_path / "out", cache_dir=cache)
    m08 = result.analysis.get("M08")
    assert m08.state.value == "ran", m08.reasons
    assert {r.measure for r in m08.measures if r.available} >= {
        "RI01",
        "RI02",
        "RI03",
        "RI04",
        "RI05",
    }
    names = {p.name for p in result.folder.iterdir()}
    assert {
        "ceded_by_treaty.csv",
        "ceded_allocation.csv",
        "reinsurance_reconciliation.csv",
    } <= names
    table = pl.read_csv(result.folder / "ceded_by_treaty.csv")
    assert set(table["treaty_id"]) >= {"QS_MOTOR_OD", "XL_TPL_L1", "SURPLUS_PROPERTY"}
    rows = pl.read_csv(result.folder / "reinsurance_reconciliation.csv")
    assert rows.filter(pl.col("differs"))["treaty_id"].n_unique() >= 1
