"""Column mapping layers (blueprint 6.3, AL01): normalise, dictionary, fuzzy, value profile."""

import polars as pl
import pytest

from actuarycanary.recognition.columns import ColumnMapping, Layer, map_columns
from actuarycanary.spec.labels import normalise_label
from tests.recognition.build import DICTIONARY, table, valuations


def _map(columns: dict[str, list], concept: str = "claim_valuations") -> dict[str, ColumnMapping]:
    raw = table(columns)
    return {m.source: m for m in map_columns(raw.frame, raw.headers, concept, DICTIONARY)}


@pytest.mark.parametrize(
    ("header", "token"),
    [
        ("İHBAR TARİHİ", "ihbartarihi"),
        ("ihbar tarihi", "ihbartarihi"),
        ("IHBAR_TARIHI", "ihbartarihi"),
        ("ıhbar tarıhı", "ihbartarihi"),
        ("Hasar Durumu ", "hasardurumu"),
        ("ŞİRKET-KODU", "sirketkodu"),
        ("Ödenen  Hasar", "odenenhasar"),
        ("Müşteri No.", "musterino"),
        ("Gİder Türü", "giderturu"),
    ],
)
def test_normalisation_folds_turkish_letters_accents_punctuation_and_spaces(
    header: str, token: str
) -> None:
    assert normalise_label(header) == token


def test_canonical_names_map_at_the_canonical_layer() -> None:
    mapped = _map(valuations())
    assert {m.field for m in mapped.values()} == set(valuations())
    assert {m.layer for m in mapped.values()} == {Layer.CANONICAL}


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("HASAR NO", "claim_id"),
        ("Hasar_No", "claim_id"),
        ("DEĞERLEME TARİHİ", "valuation_date"),
        ("degerleme tarihi", "valuation_date"),
        ("DEGERLEME TARIHI", "valuation_date"),
        ("ÖDENEN HASAR", "paid_to_date"),
        ("odenen hasar", "paid_to_date"),
        ("MUALLAK", "case_reserve"),
        ("STATÜ SON", "status"),
        ("STATUSON", "status"),
        ("Para Birimi", "currency"),
        ("PARA BİRİMİ", "currency"),
    ],
)
def test_dictionary_layer_matches_turkish_and_english_aliases(header: str, field: str) -> None:
    mapped = _map(valuations(**{field: header}))
    assert mapped[header].field == field
    assert mapped[header].layer is Layer.DICTIONARY
    assert mapped[header].confidence == 1.0


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("HASARR NO", "claim_id"),  # doubled letter
        ("DEĞERLEME TARHİ", "valuation_date"),  # missing letter, Turkish İ
        ("ÖDNEEN HASAR", "paid_to_date"),  # swapped letters
        ("MUALLAKK TUTARI", "case_reserve"),
    ],
)
def test_fuzzy_layer_matches_misspelt_headers(header: str, field: str) -> None:
    mapped = _map(valuations(**{field: header}))
    assert mapped[header].field == field
    assert mapped[header].layer is Layer.FUZZY
    assert 0.85 <= mapped[header].confidence < 1.0
    assert "close to" in mapped[header].evidence


def test_short_headers_are_never_matched_fuzzily() -> None:
    mapped = _map({**valuations(), "PBX": ["a", "b", "c", "d"]})  # one letter from "PB"
    assert mapped["PBX"].field is None
    assert mapped["PBX"].layer is Layer.NONE


def test_value_profile_rejects_a_name_match_of_the_wrong_type() -> None:
    columns = valuations()
    columns["DEĞERLEME TARİHİ"] = ["A", "B", "C", "D"]  # a date alias over text
    del columns["valuation_date"]
    mapped = _map(columns)
    assert mapped["DEĞERLEME TARİHİ"].field is None
    assert "rejected: only 0% dates" in mapped["DEĞERLEME TARİHİ"].evidence


def test_value_profile_confirms_and_records_evidence() -> None:
    mapped = _map(valuations(status="DURUM", currency="DÖVİZ"))
    assert "100% three-letter codes" in mapped["DÖVİZ"].evidence
    assert "100% of distinct labels recognised" in mapped["DURUM"].evidence
    assert "100% dates" in mapped["valuation_date"].evidence


def test_currency_is_proposed_from_values_alone() -> None:
    mapped = _map(valuations(currency="XQ1"))
    assert mapped["XQ1"].field == "currency"
    assert mapped["XQ1"].layer is Layer.VALUES
    assert mapped["XQ1"].confidence < 1.0


def test_one_column_per_field_highest_confidence_wins() -> None:
    columns = {**valuations(), "HASAR NUMARASI": ["1", "1", "2", "3"]}
    del columns["claim_id"]
    columns["HASARR NO"] = ["1", "1", "2", "3"]
    mapped = _map(columns)
    assert mapped["HASAR NUMARASI"].field == "claim_id"  # exact alias beats fuzzy
    assert mapped["HASARR NO"].field is None
    assert "already taken by 'HASAR NUMARASI'" in mapped["HASARR NO"].evidence


def test_aliases_are_read_per_concept() -> None:
    columns = {"TİP": ["İADE", "ZEYL"], "TUTAR": [1.0, 2.0]}
    premiums = _map(columns, "premiums")
    market = _map({"TİP": ["SPOT", "TÜFE"], "DEĞER": [1.0, 2.0]}, "market")
    assert premiums["TİP"].field == "type"
    assert premiums["TUTAR"].field == "amount"
    assert market["TİP"].field == "kind"


def test_columns_without_a_header_are_not_mapped() -> None:
    raw = table({**valuations(), "__UNNAMED__6": [None, None, None, None]})
    frame = raw.frame.with_columns(pl.col("__UNNAMED__6").cast(pl.String))
    mapped = map_columns(frame, raw.headers, "claim_valuations", DICTIONARY)
    assert mapped[-1].evidence == "empty column without a header"
