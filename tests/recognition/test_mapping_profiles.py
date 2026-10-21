"""Mapping profiles (blueprint 6.3): saved, read back, applied and edited."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.recognition.columns import Layer
from actuarycanary.recognition.mapping_profiles import (
    MappingProfile,
    ProfileError,
    dump_profile,
    fingerprint,
    load_profile,
    profile_path,
    profile_sha256,
    save_profile,
)
from actuarycanary.recognition.tables import (
    Source,
    canonical_table,
    recognise_table,
    to_profile,
    with_concept,
    with_field,
    with_profile,
)
from tests.recognition.build import DICTIONARY, table, valuations

DAY = date(2026, 10, 21)
MESSY = valuations(claim_id="HASARR NO", status="DURUM", currency="DÖVİZ")


def _recognised(columns: dict | None = None):
    raw = table({**(columns or MESSY), "TCKN": ["12345678901"] * 4})
    return raw, recognise_table(raw, "hasar.xlsx", DICTIONARY)


def test_fingerprint_ignores_column_order_but_not_text() -> None:
    assert fingerprint(("A", "B")) == fingerprint(("B", "A"))
    assert fingerprint(("A", "B")) != fingerprint(("A", "B "))
    assert len(fingerprint(("A",))) == 16


def test_profile_round_trips_through_its_file(tmp_path: Path) -> None:
    _, rec = _recognised()
    profile = to_profile(rec, DAY)
    path = save_profile(tmp_path, profile)
    assert path == profile_path(tmp_path, rec.fingerprint)
    loaded = load_profile(tmp_path, rec.fingerprint)
    assert loaded is not None
    assert loaded[0] == profile
    assert loaded[1] == profile_sha256(profile)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Mapping profile")
    assert "HASARR NO" in text and "field: claim_id" in text  # readable as written


HEADER_TEXT = st.text(alphabet="abcçğıiİöşüABCÇĞIÖŞÜ _-./:#'0123456789", min_size=1, max_size=12)


@given(st.lists(HEADER_TEXT, min_size=1, max_size=6, unique=True))
def test_any_header_set_round_trips(headers: list[str]) -> None:
    profile = MappingProfile(
        fingerprint=fingerprint(headers),
        concept=None,
        confirmed_on=DAY,
        headers=headers,
        columns=[],
    )
    again = MappingProfile.model_validate(yaml.safe_load(dump_profile(profile)))
    assert again == profile


def test_missing_profile_is_none_and_a_broken_one_is_an_error(tmp_path: Path) -> None:
    assert load_profile(tmp_path, "0" * 16) is None
    assert load_profile(None, "0" * 16) is None
    profile_path(tmp_path, "1" * 16).write_text("fingerprint: x\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(tmp_path, "1" * 16)


def test_saved_profile_is_applied_and_personal_data_still_dropped(tmp_path: Path) -> None:
    raw, rec = _recognised()
    profile = to_profile(rec, DAY)
    columns = [
        c.model_copy(update={"field": "salvage_to_date"}) if c.header == "TCKN" else c
        for c in profile.columns
    ]  # an edit that tries to keep identity numbers
    edited = profile.model_copy(update={"columns": columns})
    applied = with_profile(rec, edited, "sha", DICTIONARY)
    assert applied.source is Source.SAVED
    by_source = {m.source: m for m in applied.mappings}
    assert by_source["HASARR NO"].layer is Layer.SAVED
    assert by_source["TCKN"].personal == "national_id"
    canonical, _ = canonical_table(raw, applied, DICTIONARY)
    assert "salvage_to_date" not in canonical.frame.columns


def test_profile_with_a_field_of_another_concept_is_rejected() -> None:
    _, rec = _recognised()
    profile = to_profile(rec, DAY)
    columns = [
        c.model_copy(update={"field": "occurrence_date"}) if c.header == "DURUM" else c
        for c in profile.columns
    ]
    with pytest.raises(ProfileError, match="not a field of claim_valuations"):
        with_profile(rec, profile.model_copy(update={"columns": columns}), "sha", DICTIONARY)


def test_profile_without_concept_skips_the_sheet() -> None:
    _, rec = _recognised()
    profile = to_profile(rec, DAY).model_copy(update={"concept": None})
    assert with_profile(rec, profile, "sha", DICTIONARY).source is Source.SKIPPED


def test_user_edits_move_fields_and_change_concepts() -> None:
    raw, rec = _recognised()
    edited = with_field(rec, "DURUM", None, DICTIONARY)
    assert "status" in edited.missing(DICTIONARY)
    moved = with_field(edited, "DÖVİZ", "status", DICTIONARY)
    by_source = {m.source: m for m in moved.mappings}
    assert by_source["DÖVİZ"].field == "status" and by_source["DÖVİZ"].layer is Layer.USER
    with pytest.raises(ValueError, match="personal data"):
        with_field(rec, "TCKN", "claim_id", DICTIONARY)
    with pytest.raises(ValueError, match="not a field"):
        with_field(rec, "DURUM", "occurrence_date", DICTIONARY)
    claims = with_concept(rec, "claims", raw, DICTIONARY)
    assert claims.concept == "claims"
    assert {m.field for m in claims.mappings if m.used} == {"claim_id"}
    assert with_concept(rec, None, raw, DICTIONARY).source is Source.SKIPPED
