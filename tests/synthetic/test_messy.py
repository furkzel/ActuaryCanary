"""The messiness layer: every change is recorded and can be undone from the record."""

from datetime import date, datetime

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st
from rapidfuzz.distance import Levenshtein

from actuarycanary.synthetic.check import normalise_label
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.messy import Dictionaries, MessLog, layout_sheet, misspell
from actuarycanary.synthetic.scenario import load_with

MESSY = {
    "messiness": {
        "headers": {"style": "aliases", "canonical_share": 0.0, "misspell_share": 0.3},
        "title_rows": {"min": 2, "max": 3},
        "date_formats": {"text_share": 0.5},
        "value_labels": {"translate_share": 1.0},
        "personal_data": True,
    }
}
FORMATS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d")


@pytest.fixture(scope="module")
def dictionaries() -> Dictionaries:
    return Dictionaries()


def _claims_frame(n: int = 40) -> pl.DataFrame:
    rng = np.random.default_rng(0)
    days = [date(2024, 1, 1 + int(i)) for i in rng.integers(0, 28, n)]
    return pl.DataFrame(
        {
            "claim_id": [f"{i:08d}" for i in range(n)],
            "occurrence_date": days,
            "report_date": days,
            "segment": ["NON_LIFE", "LIFE"] * (n // 2),
            "line": ["MOTOR_OD"] * n,
            "close_date": [None] * n,
        }
    )


def _lay_out(overrides, dictionaries, frame=None, feed="claims"):
    scenario = load_with("baseline", overrides)
    log = MessLog()
    sheet = layout_sheet(
        scenario,
        dictionaries,
        Streams(1),
        feed,
        feed,
        frame if frame is not None else _claims_frame(),
        log,
        "Sheet1",
    )
    return scenario, sheet, log


@given(
    st.sampled_from(
        ["HASAR NO", "ÖDENEN HASAR TUTARI", "VALUATION DATE", "CASE RESERVE", "TC KİMLİK NO"]
    ),
    st.integers(0, 10_000),
)
def test_a_misspelling_differs_from_the_original_by_one_slip(text, seed):
    slipped = misspell(text, np.random.default_rng(seed))
    assert slipped != text and abs(len(slipped) - len(text)) <= 1
    assert slipped[0] == text[0]


def test_the_clean_layout_is_the_identity():
    dictionaries = Dictionaries()
    _, sheet, log = _lay_out({}, dictionaries)
    assert sheet.title_rows == [] and sheet.header_row == 1
    assert sheet.headers == list(_claims_frame().columns)
    assert {row["kind"] for row in log.columns} == {"canonical"}


def test_every_renamed_header_is_a_dictionary_alias(dictionaries):
    overrides = {
        "messiness": {**MESSY["messiness"], "headers": {"style": "aliases", "canonical_share": 0.0}}
    }
    _, sheet, log = _lay_out(overrides, dictionaries)
    renamed = [row for row in log.columns if row["field"]]
    assert {row["kind"] for row in renamed} == {"alias"}
    for row in renamed:
        aliases = [normalise_label(a) for a in dictionaries.columns[("claims", row["field"])]]
        assert normalise_label(row["header"]) in aliases
    assert set(sheet.headers) != set(_claims_frame().columns)


def test_a_misspelt_header_is_one_or_two_edits_from_an_alias(dictionaries):
    overrides = {
        "messiness": {
            **MESSY["messiness"],
            "headers": {"style": "aliases", "canonical_share": 0.0, "misspell_share": 1.0},
        }
    }
    _, _, log = _lay_out(overrides, dictionaries)
    for row in (r for r in log.columns if r["field"]):
        assert row["kind"] == "misspelt"
        aliases = dictionaries.columns[("claims", row["field"])]
        header = row["header"].rstrip().replace("_", " ")
        assert min(Levenshtein.distance(header, alias.replace("_", " ")) for alias in aliases) <= 3


def test_title_rows_sit_above_the_header_and_the_header_row_is_recorded(dictionaries):
    scenario, sheet, _ = _lay_out(MESSY, dictionaries)
    assert 2 <= len(sheet.title_rows) <= 3
    assert sheet.header_row == len(sheet.title_rows) + 1
    assert "Rapor tarihi" in sheet.title_rows[1][0]


def test_personal_data_columns_are_added_logged_and_look_like_personal_data(dictionaries):
    _, sheet, log = _lay_out(MESSY, dictionaries)
    personal = {r["header"]: r["kind"] for r in log.columns if r["kind"].startswith("personal")}
    assert personal == {
        "SIGORTALI_ADI": "personal:name",
        "TCKN": "personal:national_id_11_digits",
        "MUSTERI_NO": "personal:customer_number",
    }
    ids = sheet.columns[sheet.headers.index("TCKN")]
    assert all(len(v) == 11 and v.isdigit() and v[0] != "0" for v in ids)


def test_dates_written_as_text_parse_back_to_the_original_dates(dictionaries):
    frame = _claims_frame()
    _, sheet, log = _lay_out(MESSY, dictionaries, frame)
    logged = {(r["file"], r["field"]): r["text_format"] for r in log.dates}
    fmt = logged[("claims", "occurrence_date")]
    header = next(r["header"] for r in log.columns if r["field"] == "occurrence_date")
    cells = sheet.columns[sheet.headers.index(header)]
    assert any(isinstance(c, str) for c in cells) and any(isinstance(c, date) for c in cells)
    parsed = [datetime.strptime(c, fmt).date() if isinstance(c, str) else c for c in cells]
    assert parsed == frame["occurrence_date"].to_list()


def test_translated_labels_map_back_to_their_class(dictionaries):
    frame = _claims_frame()
    _, sheet, log = _lay_out(MESSY, dictionaries, frame)
    classes = {r["label"]: r["class"] for r in log.values if r["field"] == "segment"}
    header = next(r["header"] for r in log.columns if r["field"] == "segment")
    labels = sheet.columns[sheet.headers.index(header)]
    assert [classes.get(label, label) for label in labels] == frame["segment"].to_list()
    assert set(labels) != {"NON_LIFE", "LIFE"}


def test_columns_are_reordered_but_stay_aligned_with_their_headers(dictionaries):
    frame = _claims_frame()
    _, sheet, log = _lay_out(MESSY, dictionaries, frame)
    header = next(r["header"] for r in log.columns if r["field"] == "claim_id")
    assert sheet.columns[sheet.headers.index(header)] == frame["claim_id"].to_list()
    assert sheet.headers[: len(frame.columns)] != list(frame.columns)
