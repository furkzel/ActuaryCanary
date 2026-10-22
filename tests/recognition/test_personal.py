"""Personal data (CV07, AL01 personal_data): recognised by header or values and dropped."""

from typing import Any

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.recognition.columns import Layer
from actuarycanary.recognition.tables import canonical_table, recognise_table
from actuarycanary.recognition.value_profile import profile_values
from tests.recognition.build import DICTIONARY, table

ROWS = 12
NAMES = ("Ayşe Yılmaz", "Mehmet Kaya", "Fatma Demir", "Ali Çelik", "Zeynep Şahin", "Emine Öz")


def _valuations() -> dict[str, list[Any]]:
    return {
        "claim_id": [f"{i:04d}" for i in range(ROWS)],
        "valuation_date": ["2024-01-31"] * ROWS,
        "paid_to_date": [float(i) for i in range(ROWS)],
        "case_reserve": [10.0] * ROWS,
        "status": ["AÇIK"] * ROWS,
        "currency": ["TRY"] * ROWS,
    }


def _personal(columns: dict[str, list[Any]]) -> dict[str, str | None]:
    rec = recognise_table(table(columns), "claim_valuations.xlsx", DICTIONARY)
    return {m.source: m.personal for m in rec.mappings}


def test_personal_headers_are_dropped_by_kind() -> None:
    columns = {
        **_valuations(),
        "TC Kimlik No": ["x"] * ROWS,
        "Sigortalı Adı Soyadı": ["x"] * ROWS,
        "CEP_TELEFONU": ["x"] * ROWS,
        "E-Posta": ["x"] * ROWS,
        "Plaka": ["x"] * ROWS,
    }
    found = _personal(columns)
    assert found["TC Kimlik No"] == "national_id"
    assert found["Sigortalı Adı Soyadı"] == "name"
    assert found["CEP_TELEFONU"] == "phone"
    assert found["E-Posta"] == "email"
    assert found["Plaka"] == "vehicle_plate"
    assert found["claim_id"] is None


def test_personal_values_are_recognised_without_a_telling_header() -> None:
    columns = {
        **_valuations(),
        "ALAN 1": [str(10_000_000_000 + 7_919 * i) for i in range(ROWS)],
        "ALAN 2": [f"0532 {i:03d} 45 67" for i in range(ROWS)],
        "ALAN 3": [f"kisi{i}@ornek.com.tr" for i in range(ROWS)],
        "ALAN 4": [f"TR{i:024d}" for i in range(ROWS)],
        "ALAN 5": [NAMES[i % len(NAMES)] for i in range(ROWS)],
    }
    found = _personal(columns)
    assert found["ALAN 1"] == "national_id"
    assert found["ALAN 2"] == "phone"
    assert found["ALAN 3"] == "email"
    assert found["ALAN 4"] == "bank_account"
    assert found["ALAN 5"] == "name"


def test_identity_numbers_are_dropped_even_under_a_field_header() -> None:
    columns = {**_valuations(), "POLICY NO": [str(12_345_678_901 + i) for i in range(ROWS)]}
    assert _personal(columns)["POLICY NO"] == "national_id"


def test_short_codes_under_a_field_header_are_kept() -> None:
    columns = {**_valuations(), "ŞİRKET": ["Alpha Sigorta"] * ROWS}  # entity alias
    assert _personal(columns)["ŞİRKET"] is None


def test_profiles_hold_no_values() -> None:
    profile = profile_values(pl.Series(["Ayşe Yılmaz", "Ali Çelik"]))
    assert "Ayşe" not in repr(profile)


_KINDS = st.sampled_from(["header", "national_id", "email", "phone", "iban", "name"])
_HEADERS = st.sampled_from([label for _, label in DICTIONARY.personal.values()]).flatmap(
    lambda label: st.sampled_from([label, label.lower(), label.replace(" ", "_")])
)


@st.composite
def _personal_column(draw: st.DrawFn, n: int) -> tuple[str, list[str]]:
    kind = draw(_KINDS)
    seed = draw(st.integers(0, 10**6))
    values = {
        "header": [f"değer {seed + i}" for i in range(ROWS)],
        "national_id": [str(10**10 + seed * 31 + i * 7_919) for i in range(ROWS)],
        "email": [f"k{seed}.{i}@ornek.com" for i in range(ROWS)],
        "phone": [f"+90 5{(seed + i) % 10**9:09d}" for i in range(ROWS)],
        "iban": [f"TR{seed + i:024d}" for i in range(ROWS)],
        "name": [
            f"{NAMES[(seed + i) % 6]} {NAMES[(seed + 2 * i) % 6].split()[0]}" for i in range(ROWS)
        ],
    }[kind]
    header = draw(_HEADERS) if kind == "header" else f"EK ALAN {n}"
    return header, values


@pytest.mark.slow
@given(
    st.lists(st.integers(0, 3), min_size=1, max_size=3).flatmap(
        lambda ns: st.tuples(*(_personal_column(i) for i in range(len(ns))))
    )
)
def test_personal_data_never_reaches_a_canonical_frame(
    personal: tuple[tuple[str, list[str]], ...],
) -> None:
    columns = _valuations()
    added = {header: values for header, values in personal if header not in columns}
    raw = table({**columns, **added})
    rec = recognise_table(raw, "claim_valuations.xlsx", DICTIONARY)
    assert rec.concept == "claim_valuations"
    canonical, _ = canonical_table(raw, rec, DICTIONARY)
    kept = set(canonical.frame.columns) - set(SOURCE_COLUMNS)
    assert kept <= set(columns)
    assert all(m.layer is Layer.PERSONAL for m in rec.mappings if m.source in added)
    cells = {str(v) for c in kept for v in canonical.frame[c].to_list()}
    assert not cells & {v for values in added.values() for v in values}
