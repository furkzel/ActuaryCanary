"""Header-row detection (blueprint 6.1, CV07): rows built in code, no spreadsheets."""

from actuarycanary.io.header import find_header, is_typed

N = None


def test_header_in_the_first_row() -> None:
    rows = [["claim_id", "paid", "status"], ["0001", "10.5", "OPEN"], ["0002", "0", "CLOSED"]]
    header = find_header(rows)
    assert (header.row, header.rows_above) == (1, 0)


def test_title_and_note_rows_above_the_header_are_skipped() -> None:
    rows = [
        ["Alpha Sigorta - Hasar Değerleme Raporu", N, N],
        ["Rapor tarihi: 31.12.2025", N, N],
        [N, N, N],
        ["HASAR NO", "ÖDENEN", "DURUM"],
        ["0001", "2022-01-31 00:00:00", "AÇIK"],
    ]
    header = find_header(rows)
    assert (header.row, header.rows_above) == (4, 2)
    assert "2 row(s) above skipped" in header.evidence


def test_a_wide_note_row_above_the_header_is_not_taken() -> None:
    rows = [
        ["Hazırlayan", "Sürüm", N, N],  # two text cells, wide enough, but a header follows
        ["Poliçe No", "Başlangıç", "Bitiş", "Prim"],
        ["P1", "01.01.2024", "31.12.2024", "1200"],
    ]
    assert find_header(rows).row == 2


def test_rows_of_numbers_are_not_a_header() -> None:
    rows = [["2022", "2023", "2024"], ["Kod", "Tutar", "Tarih"], ["A", "1", "31.01.2024"]]
    assert find_header(rows).row == 2


def test_repeated_cells_are_not_a_header() -> None:
    rows = [["Toplam", "Toplam", "Toplam"], ["Kod", "Tutar", "Tarih"], ["A", "1", "31.01.2024"]]
    assert find_header(rows).row == 2


def test_all_text_table_falls_back_to_the_first_distinct_text_row() -> None:
    rows = [["Başlık", N, N], ["Kod", "Ad", "Grup"], ["A", "Birinci", "X"], ["B", "İkinci", "Y"]]
    header = find_header(rows)
    assert header.row == 2
    assert "no typed values" in header.evidence


def test_empty_sheet() -> None:
    assert find_header([]).evidence == "empty sheet"
    assert find_header([[N, N]]).evidence == "empty sheet"


def test_typed_cells() -> None:
    for text in ("12", "-3.5", "1,25", "1e5", "2022-01-31", "2022-01-31 00:00:00", "31.12.2025"):
        assert is_typed(text), text
    for text in ("HASAR NO", "TRY", "P-001", "Rapor tarihi: 31.12.2025"):
        assert not is_typed(text), text
