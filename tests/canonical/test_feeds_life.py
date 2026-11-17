"""Canonical form of the life feeds (records 0440, 0441): recognition of hand tables, the rules
that decide which rows enter (DV-LIF-01 to -05, DV-LEV-01 to -03, DV-FFL-01 to -04), the parsed
age band, and the personal fields CV11 keeps out (birth date always, sex unless asked)."""

from datetime import date

import polars as pl
import pytest

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.canonical.life import parse_age_band
from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.life.load import drop_sex
from actuarycanary.life.settings import LifeSettings
from actuarycanary.pipeline import RunSettings, _mapping_record
from actuarycanary.recognition.tables import canonical_table, recognise_table
from tests.recognition.build import DICTIONARY, SPECS, table

N = 6


def in_force(**changes: list) -> dict[str, list]:
    columns: dict[str, list] = {
        "SÖZLEŞME NO": [f"L{k:03d}" for k in range(N)],
        "DEĞERLEME TARİHİ": [date(2024, 12, 31)] * N,
        "ÜRÜN": ["TERM_LIFE"] * N,
        "GİRİŞ TARİHİ": [date(2020, 3, 1 + k) for k in range(N)],
        "YAŞ": ["45", "45-49", "85+", "30", "52", "61"],
        "DURUM": ["Yürürlükte", "IN_FORCE", "LAPSED", "IN_FORCE", "PAID_UP", "IN_FORCE"],
        "TEMİNAT": [1000.0 * (k + 1) for k in range(N)],
        "CİNSİYET": ["FEMALE", "MALE"] * (N // 2),
        "DOĞUM TARİHİ": [date(1980, 1, 1 + k) for k in range(N)],
    }
    return {**columns, **changes}


def _canonical(columns: dict[str, list], concept: str):
    raw = table(columns)
    rec = recognise_table(raw, "export.xlsx", DICTIONARY)
    assert rec.concept == concept, rec.rejection
    frame, _ = canonical_table(raw, rec, DICTIONARY)
    return rec, frame, canonicalise(frame, SPECS.data[concept])


def _rules(feed) -> dict[str, int]:
    return {f.rule: f.count for f in feed.findings}


def test_a_life_in_force_table_in_turkish_is_recognised_and_typed() -> None:
    rec, _, feed = _canonical(in_force(), "life_in_force")
    assert rec.rejection == ""
    frame = feed.frame.drop(SOURCE_COLUMNS)
    assert frame["valuation_date"].dtype == pl.Date and frame["entry_date"].dtype == pl.Date
    assert frame["status"].to_list()[:2] == ["IN_FORCE", "IN_FORCE"]  # label to class (AL02)
    assert frame["age_low"].to_list() == [45, 45, 85, 30, 52, 61]
    assert frame["age_high"].to_list() == [45, 49, None, 30, 52, 61]


def test_a_birth_date_is_never_read_and_is_listed() -> None:
    rec, frame, _ = _canonical(in_force(), "life_in_force")
    birth = next(m for m in rec.mappings if m.source == "DOĞUM TARİHİ")
    assert birth.personal == "birth_date" and not birth.used
    assert "DOĞUM TARİHİ" not in frame.frame.columns
    assert _mapping_record(rec, [])["personal_data_dropped"] == ["DOĞUM TARİHİ"]


def test_sex_is_dropped_on_load_and_listed_unless_the_user_asks() -> None:
    assert RunSettings().life.use_sex is False  # CV11 default
    rec, frame, _ = _canonical(in_force(), "life_in_force")
    dropped_frame, dropped = drop_sex(frame, rec, use_sex=False)
    assert "sex" not in dropped_frame.frame.columns and dropped == ("CİNSİYET",)
    record = _mapping_record(rec, [], dropped)
    assert record["personal_data_dropped"] == ["DOĞUM TARİHİ", "CİNSİYET"]
    assert ["CİNSİYET", "sex"] not in record["columns"]
    kept, none = drop_sex(frame, rec, use_sex=True)
    assert kept.frame["sex"].to_list()[:2] == ["FEMALE", "MALE"] and none == ()


def test_the_life_settings_hold_the_cv11_defaults_and_enter_the_settings_record() -> None:
    cv11 = {d.name: d.default for d in SPECS.conventions["CV11"].defaults}
    assert LifeSettings().model_dump() == cv11
    record = RunSettings(life=LifeSettings(use_sex=True)).model_dump(mode="json")
    assert record["life"]["use_sex"] is True
    assert RunSettings().model_dump(mode="json")["life"] != record["life"]
    with pytest.raises(ValueError):
        LifeSettings.model_validate({"study_cells": "month"})


@pytest.mark.parametrize(
    ("band", "low", "high", "valid"),
    [
        ("45", 45, 45, True),
        ("45-49", 45, 49, True),
        (" 45 - 49 ", 45, 49, True),
        ("85+", 85, None, True),
        ("0", 0, 0, True),
        ("120", 120, 120, True),
        ("49-45", 49, 45, False),
        ("121", 121, 121, False),
        ("45-130", 45, 130, False),
        ("forty", None, None, False),
        ("45.5", None, None, False),
    ],
)
def test_an_age_band_is_one_age_a_band_or_an_open_band(band, low, high, valid) -> None:
    frame = pl.DataFrame({"band": [band]})
    got = frame.select(*(e.alias(str(i)) for i, e in enumerate(parse_age_band(pl.col("band")))))
    assert got.row(0) == (low, high, valid)


def test_rows_the_life_in_force_rules_exclude() -> None:
    columns = in_force(
        **{
            "YAŞ": ["45", "49-45", "85+", None, "52", "61"],
            "DURUM": ["IN_FORCE", "IN_FORCE", "LAPSED", "IN_FORCE", "WHATEVER", "IN_FORCE"],
            "GİRİŞ TARİHİ": [date(2020, 3, 1)] * 5 + [date(2025, 3, 1)],
        }
    )
    _, _, feed = _canonical(columns, "life_in_force")
    assert _rules(feed) == {"DV-LIF-01": 1, "DV-LIF-02": 1, "DV-LIF-03": 1, "DV-LIF-04": 1}
    assert feed.frame["contract_id"].to_list() == ["L000", "L002"]


def test_duplicates_of_a_contract_and_valuation_keep_the_later_row() -> None:
    columns = in_force(**{"SÖZLEŞME NO": ["L1", "L1", "L2", "L2", "L3", "L4"]})
    columns["TEMİNAT"] = [1.0, 2.0, 5.0, 5.0, 1.0, 1.0]
    columns["YAŞ"] = ["45", "45", "50", "50", "30", "52"]
    columns["DURUM"] = ["IN_FORCE"] * N
    columns["GİRİŞ TARİHİ"] = [date(2020, 3, 1)] * N
    columns["CİNSİYET"] = ["FEMALE"] * N
    columns["DOĞUM TARİHİ"] = [date(1980, 1, 1)] * N
    _, _, feed = _canonical(columns, "life_in_force")
    assert [f.count for f in feed.findings if f.rule == "DV-LIF-05"] == [1, 1]
    assert feed.frame.filter(pl.col("contract_id") == "L1")["sum_assured"].to_list() == [2.0]


def test_the_life_events_rules() -> None:
    columns = {
        "OLAY NO": ["E1", "E2", "E3", "E3", None],
        "SÖZLEŞME NO": ["L1", "L2", "L3", "L3", "L4"],
        "OLAY TARİHİ": [date(2024, 5, 1)] * 5,
        "OLAY TİPİ": ["VEFAT", "DEATH", "SOMETHING", "SOMETHING", "LAPSE"],
        "TUTAR": [100.0, 100.0, 5.0, 6.0, 1.0],
    }
    _, _, feed = _canonical(columns, "life_events")
    assert _rules(feed) == {"DV-LEV-01": 1, "DV-LEV-02": 2, "DV-LEV-03": 1}
    assert feed.frame["event_type"].to_list() == ["DEATH", "DEATH", "UNMAPPED"]


def test_the_fund_flows_rules_and_the_switch_sign() -> None:
    columns = {
        "FLOW ID": ["F1", "F2", "F3", "F4", "F5"],
        "SÖZLEŞME NO": ["P1"] * 5,
        "VALÖR": [date(2024, 5, 1)] * 5,
        "TUTAR": [100.0, -40.0, 40.0, None, 10.0],
        "PARA BİRİMİ": ["TRY", "TRY", "TRY", "TRY", "XX"],
        "HAREKET TİPİ": ["CONTRIBUTION", "FUND_SWITCH", "FUND_SWITCH", "FEE", "FEE"],
        "FON KODU": [None, "A", "B", None, None],
    }
    _, _, feed = _canonical(columns, "fund_flows")
    assert _rules(feed) == {"DV-FFL-01": 1, "DV-FFL-03": 1}
    # the sign of a switch is kept: negative out of fund A, positive into fund B (DV-FFL-06)
    assert feed.frame["amount"].to_list() == [100.0, -40.0, 40.0, 10.0]
    assert feed.frame["currency"].to_list()[-1] == "UNKNOWN"
