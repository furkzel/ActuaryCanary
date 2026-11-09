"""The folder browser lists names and counts files; it reads no file and writes nothing."""

from pathlib import Path

import pytest

from actuarycanary.ui import folders


def _touch(folder: Path, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"")


def test_spreadsheets_and_csv_are_counted_and_lock_files_are_not(tmp_path: Path) -> None:
    _touch(tmp_path, "a.xlsx", "b.XLSX", "c.xls", "d.ods", "e.csv", "f.txt", "~$a.xlsx")
    counts = folders.count_files(tmp_path)
    assert counts == folders.Counts(spreadsheets=4, csv=1)


def test_a_missing_folder_has_no_counts(tmp_path: Path) -> None:
    assert folders.count_files(tmp_path / "nowhere") is None


def test_browse_lists_subfolders_with_counts_and_the_parent(tmp_path: Path) -> None:
    _touch(tmp_path / "claims", "claim_valuations.xlsx", "premiums.xlsx", "notes.csv")
    _touch(tmp_path / "empty")
    _touch(tmp_path / ".hidden")
    _touch(tmp_path, "loose.xlsx")
    shown = folders.browse(str(tmp_path))
    assert shown["path"] == str(tmp_path.resolve())
    assert shown["parent"] == str(tmp_path.resolve().parent)
    assert shown["counts"] == {"spreadsheets": 1, "csv": 0}
    listed = {f["name"]: f["counts"] for f in shown["folders"]}  # type: ignore[union-attr]
    assert listed == {
        "claims": {"spreadsheets": 2, "csv": 1},
        "empty": {"spreadsheets": 0, "csv": 0},
    }


def test_browse_without_a_path_gives_the_roots() -> None:
    shown = folders.browse(None)
    assert shown["path"] == "" and shown["parent"] is None
    assert shown["roots"] and shown["folders"] == []


def test_browse_of_a_file_or_a_missing_path_is_an_error(tmp_path: Path) -> None:
    _touch(tmp_path, "a.xlsx")
    with pytest.raises(FileNotFoundError):
        folders.browse(str(tmp_path / "a.xlsx"))
    with pytest.raises(FileNotFoundError):
        folders.browse(str(tmp_path / "nowhere"))


def test_browse_writes_nothing(tmp_path: Path) -> None:
    _touch(tmp_path / "x", "a.xlsx")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    folders.browse(str(tmp_path))
    folders.browse(str(tmp_path / "x"))
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_the_counting_budget_is_spent_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a", "b"):
        _touch(tmp_path / name, "x.xlsx")
    monkeypatch.setattr(folders, "COUNT_BUDGET_SECONDS", -1.0)
    shown = folders.browse(str(tmp_path))
    assert [f["counts"] for f in shown["folders"]] == [None, None]  # type: ignore[union-attr]
