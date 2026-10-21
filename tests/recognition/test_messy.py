"""The messy_headers tiny files map to the same canonical frames as baseline tiny (same seed).

Scored against the scenario's truth: header rows (layout.csv), column map (column_map.csv)
and personal-data columns (personal_data_columns.csv).
"""

from pathlib import Path

import polars as pl
import pytest

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.io.excel import SOURCE_COLUMNS, RawTable, read_workbook, spreadsheets
from actuarycanary.recognition.tables import TableRecognition, canonical_table, recognise_table
from tests.recognition.build import DICTIONARY, SPECS

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"
BASELINE, MESSY = FIXTURES / "baseline", FIXTURES / "messy_headers"
CACHE = Path(__file__).parents[2] / ".cache"  # the project's reader cache, keyed by content

pytestmark = pytest.mark.integration

Recognised = list[tuple[RawTable, TableRecognition]]


def _recognise(folder: Path, cache: Path) -> Recognised:
    return [
        (table, recognise_table(table, path.name, DICTIONARY))
        for path in spreadsheets(folder)
        for table in read_workbook(path, cache).tables
    ]


def _canonical(recognised: Recognised) -> dict[str, pl.DataFrame]:
    """Canonical frame per concept, source columns dropped, identical rows kept once (the
    messy files repeat 1% of rows)."""
    parts: dict[str, list[pl.DataFrame]] = {}
    for table, rec in recognised:
        assert rec.concept is not None
        raw, _ = canonical_table(table, rec, DICTIONARY)
        feed = canonicalise(raw, SPECS.data[rec.concept])
        parts.setdefault(rec.concept, []).append(feed.frame.drop(SOURCE_COLUMNS))
    return {
        concept: pl.concat(frames, how="diagonal_relaxed").unique(maintain_order=True)
        for concept, frames in parts.items()
    }


@pytest.fixture(scope="module")
def recognised() -> tuple[Recognised, Recognised]:
    return _recognise(BASELINE, CACHE), _recognise(MESSY, CACHE)


def test_messy_maps_to_the_same_canonical_frames_as_baseline(
    recognised: tuple[Recognised, Recognised],
) -> None:
    baseline, messy = (_canonical(r) for r in recognised)
    assert set(messy) == set(baseline) == set(SPECS.data)
    for concept, expected in baseline.items():
        got = messy[concept].select(expected.columns)
        assert got.schema == expected.schema, concept
        assert got.equals(expected), concept


def test_header_rows_columns_and_personal_data_match_the_truth(
    recognised: tuple[Recognised, Recognised],
) -> None:
    _, messy = recognised
    layout = pl.read_csv(MESSY / "truth" / "layout.csv")
    truth = pl.read_csv(MESSY / "truth" / "column_map.csv").with_columns(
        pl.col("field").fill_null("")
    )
    by_sheet = {(rec.file, rec.sheet): rec for _, rec in messy}
    for row in layout.iter_rows(named=True):
        assert by_sheet[(row["file"], row["sheet"])].header_row == row["header_row"]
    mapped = {
        (rec.concept, rec.sheet, m.source): (m.field or "", m.personal)
        for _, rec in messy
        for m in rec.mappings
    }
    for row in truth.iter_rows(named=True):
        field, personal = mapped[(row["file"], row["sheet"], row["header"])]
        assert field == row["field"], row
        assert (personal is not None) == row["kind"].startswith("personal:"), row


def test_baseline_layouts_are_canonical(recognised: tuple[Recognised, Recognised]) -> None:
    baseline, messy = recognised
    assert {str(rec.source) for _, rec in baseline} == {"canonical"}
    assert {str(rec.source) for _, rec in messy} == {"automatic"}
