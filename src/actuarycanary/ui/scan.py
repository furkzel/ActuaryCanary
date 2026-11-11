"""What the program recognised in a folder, for the mapping screen, and the saving of a mapping.

`scan_file` does for a file what `pipeline.recognise_folder` does (read, recognise, apply a saved
profile, detect the amounts) but reports a file that cannot be read instead of stopping, so that
the screen can say why. A confirmed mapping is saved as the command line saves it: `to_profile`
and `save_profile` into the profiles folder, keyed by the fingerprint of the headers (record
0702).
"""

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from actuarycanary.io.excel import RawTable, read_workbook, spreadsheets
from actuarycanary.recognition.amounts import detect_amounts
from actuarycanary.recognition.dictionary import Dictionary, build_dictionary
from actuarycanary.recognition.mapping_profiles import (
    MappingProfile,
    ProfileError,
    load_profile,
    save_profile,
)
from actuarycanary.recognition.tables import (
    Source,
    TableRecognition,
    recognise_table,
    to_profile,
    with_amounts,
    with_concept,
    with_field,
    with_profile,
)
from actuarycanary.spec.loader import load_specs


class ScanError(ValueError):
    """The request cannot be answered; `code` names the message of the page."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Sheet:
    recognition: TableRecognition
    table: RawTable


@dataclass(frozen=True)
class FileScan:
    name: str
    sheets: tuple[Sheet, ...] = ()
    error: str | None = None  # the file could not be read: the reason
    empty_sheets: int = 0  # sheets without a header row


def dictionary() -> Dictionary:
    return build_dictionary(load_specs())


def folder_of(text: str) -> Path:
    """The folder named by the person, which must exist."""
    if not text.strip():
        raise ScanError("folder_empty")
    folder = Path(text.strip()).expanduser()
    if not folder.is_dir():
        raise ScanError("folder_missing", str(folder))
    return folder


def scan_file(
    path: Path, d: Dictionary, cache_dir: Path | None, profiles_dir: Path | None
) -> FileScan:
    """Read and recognise every sheet of one spreadsheet."""
    try:
        workbook = read_workbook(path, cache_dir)
    except Exception as error:  # a locked, damaged or foreign file: say why and go on
        return FileScan(path.name, error=f"{type(error).__name__}: {error}")
    sheets: list[Sheet] = []
    empty = 0
    for table in workbook.tables:
        if not table.headers:
            empty += 1
            continue
        rec = recognise_table(table, workbook.name, d)
        if rec.source is not Source.CANONICAL:
            saved = load_profile(profiles_dir, rec.fingerprint)
            if saved is not None:
                rec = with_profile(rec, saved[0], saved[1], d)
        sheets.append(Sheet(detect_amounts(rec, table), table))
    return FileScan(workbook.name, tuple(sheets), None, empty)


def scan_folder(
    folder: Path, d: Dictionary, cache_dir: Path | None, profiles_dir: Path | None
) -> list[FileScan]:
    """`scan_file` for every spreadsheet directly in `folder`."""
    return [scan_file(path, d, cache_dir, profiles_dir) for path in spreadsheets(folder)]


def _find(
    folder: Path,
    d: Dictionary,
    cache_dir: Path | None,
    profiles_dir: Path | None,
    file: str,
    sheet: str,
) -> Sheet:
    if not file or Path(file).name != file:
        raise ScanError("sheet_missing", file)
    path = folder / file
    if not path.is_file():
        raise ScanError("sheet_missing", f"{file} [{sheet}]")
    for item in scan_file(path, d, cache_dir, profiles_dir).sheets:
        if item.recognition.sheet == sheet:
            return item
    raise ScanError("sheet_missing", f"{file} [{sheet}]")


def _state(rec: TableRecognition) -> str:
    if rec.source is Source.CANONICAL:
        return "canonical"
    if rec.source is Source.SAVED:
        return "saved"
    if rec.concept is None:
        return "skipped" if rec.source is Source.SKIPPED else "not_recognised"
    return "proposed"


def reason_not_recognised(rec: TableRecognition) -> str:
    """Why a sheet has no concept, in the words of the recogniser (English)."""
    if rec.source is Source.SKIPPED:
        return "skipped by a saved mapping profile or by choice"
    if rec.rejection:
        return rec.rejection  # the best guess and every reason it was rejected (record 0375)
    if not rec.candidates:
        return "no concept recognised"
    return f"best candidate {rec.candidates[0].describe()} was not accepted"


def sheet_json(sheet: Sheet, d: Dictionary) -> dict[str, Any]:
    """One sheet for the page: the recognition as the terminal confirmation shows it."""
    rec = sheet.recognition
    spec = d.concepts.get(rec.concept) if rec.concept else None
    chosen = next((c for c in rec.candidates if c.concept == rec.concept), None)
    return {
        "file": rec.file,
        "sheet": rec.sheet,
        "fingerprint": rec.fingerprint,
        "state": _state(rec),
        "editable": rec.source is not Source.CANONICAL,
        "concept": rec.concept,
        "score": None if chosen is None else round(chosen.score, 3),
        "detail": None if chosen is None else chosen.detail(),
        "reason": reason_not_recognised(rec) if rec.concept is None else "",
        "header_row": rec.header_row,
        "rows_above": rec.rows_above,
        "header_evidence": rec.header_evidence,
        "candidates": [
            {"concept": c.concept, "score": round(c.score, 3), "detail": c.detail()}
            for c in rec.candidates
        ],
        "amounts": rec.amounts if rec.concept == "claim_valuations" else None,
        "amounts_note": rec.amounts_note,
        "missing": rec.missing(d),
        "required": [f.name for f in spec.fields if f.required] if spec else [],
        "fields": [
            {"name": f.name, "required": f.required, "type": f.type, "description": f.description}
            for f in (spec.fields if spec else [])
        ],
        "mappings": [
            {
                "source": m.source,
                "field": m.field if m.used else None,
                "layer": str(m.layer),
                "confidence": round(m.confidence, 3) if m.field else None,
                "evidence": m.evidence,
                "personal": m.personal,
            }
            for m in rec.mappings
        ],
    }


def scan_json(scans: list[FileScan], d: Dictionary, folder: Path) -> dict[str, Any]:
    """The whole recognition for the page: recognised sheets, and the files that are not."""
    files = [
        {
            "name": scan.name,
            "error": scan.error,
            "empty_sheets": scan.empty_sheets,
            "recognised": any(s.recognition.concept is not None for s in scan.sheets),
            "sheets": [sheet_json(s, d) for s in scan.sheets],
        }
        for scan in scans
    ]
    return {
        "folder": str(folder),
        "files": files,
        "concepts": [
            {"concept": name, "file_name": spec.file_name, "required": spec.required_for_report}
            for name, spec in d.concepts.items()
        ],
        "pending": sum(
            1 for s in scans for t in s.sheets if t.recognition.source is Source.AUTOMATIC
        ),
    }


def with_choice(
    sheet: Sheet,
    d: Dictionary,
    concept: str | None,
    amounts: str | None,
    columns: dict[str, str | None] | None,
) -> TableRecognition:
    """The recognition with the person's choices applied as the terminal edit does: the concept
    first (mapped again, the amounts looked at again), then the amounts, then each column that
    differs; columns set to unused go first so that a field can move to another column."""
    rec = sheet.recognition
    wanted = columns or {}
    try:
        if concept != rec.concept:
            rec = detect_amounts(with_concept(rec, concept, sheet.table, d), sheet.table)
        if rec.concept is None:
            return rec
        if amounts and rec.concept == "claim_valuations" and amounts != rec.amounts:
            rec = with_amounts(rec, amounts)
        personal = {m.source for m in rec.mappings if m.personal is not None}
        current = {m.source: m.field if m.used else None for m in rec.mappings}
        changes = [(h, t) for h, t in wanted.items() if h in current and current[h] != t]
        for header, target in sorted(changes, key=lambda c: c[1] is not None):
            if header not in personal:  # personal data is dropped whatever is asked
                rec = with_field(rec, header, target, d)
    except ValueError as error:
        raise ScanError("mapping_rejected", str(error)) from error
    final = {m.source: m.field if m.used else None for m in rec.mappings}
    wrong = [h for h, t in wanted.items() if h in final and h not in personal and final[h] != t]
    if wrong:
        raise ScanError("mapping_conflict", ", ".join(wrong))
    return rec


def save_choices(
    folder: Path,
    d: Dictionary,
    cache_dir: Path | None,
    profiles_dir: Path,
    choices: list[dict[str, Any]],
    today: date | None = None,
) -> list[Path]:
    """Save a confirmed mapping profile for each sheet of `choices` (file, sheet, concept,
    amounts, columns); return the files written. A sheet in the canonical layout has nothing to
    confirm and is left alone."""
    day = today or date.today()
    profiles: dict[str, MappingProfile] = {}
    for choice in choices:
        file, name = str(choice.get("file", "")), str(choice.get("sheet", ""))
        sheet = _find(folder, d, cache_dir, profiles_dir, file, name)
        if sheet.recognition.source is Source.CANONICAL:
            continue
        rec = with_choice(
            sheet, d, choice.get("concept") or None, choice.get("amounts"), choice.get("columns")
        )
        rec = replace(rec, source=Source.SKIPPED if rec.concept is None else Source.CONFIRMED)
        profile = to_profile(rec, day)
        if profiles.setdefault(rec.fingerprint, profile) != profile:
            raise ScanError("profile_conflict", rec.label)  # same headers, two different answers
    written: list[Path] = []
    for profile in profiles.values():
        try:
            written.append(save_profile(profiles_dir, profile))
        except (OSError, ProfileError) as error:
            raise ScanError("profile_not_saved", str(error)) from error
    return written


def sheet_after_concept(
    folder: Path,
    d: Dictionary,
    cache_dir: Path | None,
    profiles_dir: Path | None,
    file: str,
    sheet: str,
    concept: str | None,
) -> dict[str, Any]:
    """One sheet mapped again for another concept (None: skipped); nothing is saved."""
    item = _find(folder, d, cache_dir, profiles_dir, file, sheet)
    if item.recognition.source is Source.CANONICAL:
        raise ScanError("sheet_not_editable", f"{file} [{sheet}]")
    return sheet_json(Sheet(with_choice(item, d, concept, None, None), item.table), d)
