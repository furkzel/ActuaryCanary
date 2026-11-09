"""What the mapping screen shows and the saving of a confirmed mapping (record 0702)."""

from pathlib import Path

import pytest

from actuarycanary.pipeline import recognise_folder
from actuarycanary.recognition.mapping_profiles import fingerprint, read_profile
from actuarycanary.recognition.tables import Source
from actuarycanary.ui import scan
from actuarycanary.ui.runner import CACHE_NAME

from .conftest import BASELINE_TINY, MESSY


@pytest.fixture(scope="module")
def dictionary():
    return scan.dictionary()


@pytest.fixture(scope="module")
def messy(messy_out: Path, dictionary):
    return scan.scan_folder(MESSY, dictionary, messy_out / CACHE_NAME, None)


def _sheet(scans, file: str, sheet: str):
    return next(
        s for f in scans if f.name == file for s in f.sheets if s.recognition.sheet == sheet
    )


def _columns(item) -> dict[str, str | None]:
    return {m.source: (m.field if m.used else None) for m in item.recognition.mappings}


def test_the_messy_example_shows_concept_header_row_and_a_mapping_per_column(messy, dictionary):
    item = _sheet(messy, "claim_valuations.xlsx", "Hasar")
    shown = scan.sheet_json(item, dictionary)
    assert shown["concept"] == "claim_valuations" and shown["state"] == "proposed"
    assert shown["header_row"] == 4 and shown["rows_above"] == 3
    assert shown["score"] is not None and 0 < shown["score"] <= 1
    assert len(shown["mappings"]) == len(item.table.headers)
    status = next(m for m in shown["mappings"] if m["source"] == "HASAR_DURUMU")
    assert status["field"] == "status" and status["layer"] == "dictionary"
    assert shown["editable"] and "claim_id" in [f["name"] for f in shown["fields"]]
    assert shown["required"] and shown["missing"] == []


def test_personal_data_columns_are_shown_as_dropped(messy, dictionary):
    shown = scan.sheet_json(_sheet(messy, "claims.xlsx", "Hasar Listesi"), dictionary)
    personal = [m for m in shown["mappings"] if m["personal"]]
    assert personal and all(m["field"] is None for m in personal)


def test_a_canonical_layout_has_nothing_to_confirm(dictionary, messy_out):
    scans = scan.scan_folder(BASELINE_TINY, dictionary, messy_out / CACHE_NAME, None)
    shown = scan.sheet_json(_sheet(scans, "claim_valuations.xlsx", "claim_valuations"), dictionary)
    assert shown["state"] == "canonical" and not shown["editable"]


def test_the_scan_is_what_the_pipeline_recognises(messy, dictionary, messy_out):
    loaded = recognise_folder(MESSY, dictionary, messy_out / CACHE_NAME, None)
    ours = {(f.name, s.recognition.sheet): s.recognition for f in messy for s in f.sheets}
    assert set(ours) == {(t.recognition.file, t.recognition.sheet) for t in loaded}
    for item in loaded:
        mine = ours[(item.recognition.file, item.recognition.sheet)]
        assert mine.concept == item.recognition.concept
        assert mine.mappings == item.recognition.mappings
        assert mine.source == item.recognition.source and mine.amounts == item.recognition.amounts


def test_a_file_that_cannot_be_read_is_reported_with_its_reason(dictionary, tmp_path: Path):
    (tmp_path / "broken.xlsx").write_bytes(b"this is not a workbook")
    (tmp_path / "~$locked.xlsx").write_bytes(b"lock file of an open workbook")
    scans = scan.scan_folder(tmp_path, dictionary, None, None)
    assert [s.name for s in scans] == ["broken.xlsx"]  # the lock file is not a workbook
    assert scans[0].error and not scans[0].sheets
    shown = scan.scan_json(scans, dictionary, tmp_path)
    assert shown["files"][0]["recognised"] is False and shown["files"][0]["error"]


def test_a_folder_is_checked_before_it_is_scanned(tmp_path: Path):
    with pytest.raises(scan.ScanError) as empty:
        scan.folder_of("  ")
    assert empty.value.code == "folder_empty"
    with pytest.raises(scan.ScanError) as missing:
        scan.folder_of(str(tmp_path / "nowhere"))
    assert missing.value.code == "folder_missing"
    assert scan.folder_of(str(tmp_path)) == tmp_path


def test_changing_the_concept_maps_the_sheet_again_and_saves_nothing(
    dictionary, messy_out: Path, tmp_path: Path
):
    shown = scan.sheet_after_concept(
        MESSY, dictionary, messy_out / CACHE_NAME, tmp_path, "expenses.xlsx", "Giderler", None
    )
    assert shown["concept"] is None and shown["state"] == "skipped"
    assert list(tmp_path.iterdir()) == []


def test_a_mapping_edit_is_saved_where_the_command_line_reads_it(
    messy_one, dictionary, messy_out: Path, tmp_path: Path
):
    """Edit, save, scan again, and the recognition of the pipeline uses the saved profile."""
    profiles = tmp_path / "profiles"
    cache = messy_out / CACHE_NAME
    item = _sheet(
        scan.scan_folder(messy_one, dictionary, cache, None), "claim_valuations.xlsx", "Hasar"
    )
    columns = _columns(item)
    columns["RUCU TAHSILAT "] = None  # leave an optional column out
    choice = {
        "file": "claim_valuations.xlsx",
        "sheet": "Hasar",
        "concept": "claim_valuations",
        "amounts": "to_date",
        "columns": columns,
    }
    written = scan.save_choices(messy_one, dictionary, cache, profiles, [choice])
    key = fingerprint(item.table.headers)
    assert written == [profiles / f"{key}.yaml"]
    profile, _ = read_profile(written[0])
    assert profile.field_of("RUCU TAHSILAT ") is None and profile.concept == "claim_valuations"

    again = scan.scan_folder(messy_one, dictionary, cache, profiles)
    saved = _sheet(again, "claim_valuations.xlsx", "Hasar").recognition
    assert saved.source is Source.SAVED
    assert next(m for m in saved.mappings if m.source == "RUCU TAHSILAT ").field is None

    used_by_pipeline = recognise_folder(messy_one, dictionary, cache, profiles)
    mine = next(t.recognition for t in used_by_pipeline if t.recognition.sheet == "Hasar")
    assert mine.source is Source.SAVED and mine.mappings == saved.mappings
    assert mine.profile_sha256


def test_moving_a_field_to_another_column_frees_the_first_one(messy, dictionary):
    item = _sheet(messy, "claim_valuations.xlsx", "Hasar")
    columns = _columns(item)
    paid = next(h for h, f in columns.items() if f == "paid_to_date")
    other = next(h for h, f in columns.items() if f == "case_reserve")
    columns[paid], columns[other] = "case_reserve", "paid_to_date"
    rec = scan.with_choice(item, dictionary, "claim_valuations", None, columns)
    final = {m.source: m.field for m in rec.mappings}
    assert final[paid] == "case_reserve" and final[other] == "paid_to_date"


def test_a_field_asked_for_by_two_columns_is_a_conflict(messy, dictionary):
    item = _sheet(messy, "claim_valuations.xlsx", "Hasar")
    columns = _columns(item)
    taken = [h for h, f in columns.items() if f][:2]
    columns[taken[0]] = columns[taken[1]]
    with pytest.raises(scan.ScanError) as error:
        scan.with_choice(item, dictionary, "claim_valuations", None, columns)
    assert error.value.code == "mapping_conflict"


def test_an_unknown_field_or_concept_is_refused(messy, dictionary):
    item = _sheet(messy, "claim_valuations.xlsx", "Hasar")
    header = item.table.headers[0]
    with pytest.raises(scan.ScanError) as field:
        scan.with_choice(item, dictionary, "claim_valuations", None, {header: "no_such_field"})
    assert field.value.code == "mapping_rejected"
    with pytest.raises(scan.ScanError) as concept:
        scan.with_choice(item, dictionary, "no_such_concept", None, None)
    assert concept.value.code == "mapping_rejected"


def test_two_sheets_with_the_same_headers_cannot_be_given_two_answers(
    messy, dictionary, tmp_path: Path, messy_out: Path
):
    item = _sheet(messy, "claim_valuations.xlsx", "Hasar")
    first = {
        "file": "claim_valuations.xlsx",
        "sheet": "Hasar",
        "concept": "claim_valuations",
        "columns": _columns(item),
    }
    second = {**first, "concept": None}
    with pytest.raises(scan.ScanError) as error:
        scan.save_choices(
            MESSY, dictionary, messy_out / CACHE_NAME, tmp_path / "p", [first, second]
        )
    assert error.value.code == "profile_conflict"
    assert not (tmp_path / "p").exists()


def test_a_file_name_cannot_leave_the_folder(dictionary):
    with pytest.raises(scan.ScanError) as error:
        scan.sheet_after_concept(MESSY, dictionary, None, None, "../x.xlsx", "s", None)
    assert error.value.code == "sheet_missing"
