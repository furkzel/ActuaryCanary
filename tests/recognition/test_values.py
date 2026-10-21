"""Value recognition (blueprint 6.4, AL02): labels to classes, unknown labels listed."""

import polars as pl

from actuarycanary.canonical.feeds import UNMAPPED
from actuarycanary.recognition.values import map_labels, map_values
from tests.recognition.build import DICTIONARY


def test_turkish_and_english_labels_map_to_classes() -> None:
    lookup = DICTIONARY.values[("claim_valuations", "status")]
    labels = ["AÇIK", "açık", "ACIK", "Devam Ediyor", "kapandı", "KAPANDI", "Yeniden Açıldı"]
    labels += ["İHTİLAFLI", "ihtilafli", "Reddedildi", "CLOSED_NIL", "OPEN", "settled"]
    values, report = map_labels(pl.Series("status", labels), lookup)
    assert values.to_list() == [
        "OPEN",
        "OPEN",
        "OPEN",
        "OPEN",
        "CLOSED",
        "CLOSED",
        "REOPENED",
        "LITIGATED",
        "LITIGATED",
        "CLOSED_NIL",
        "CLOSED_NIL",
        "OPEN",
        "CLOSED",
    ]
    assert report.unmapped == ()
    assert ("KAPANDI", "CLOSED", 1) in report.mapped


def test_unknown_labels_become_unmapped_and_are_listed_with_counts() -> None:
    lookup = DICTIONARY.values[("claim_valuations", "status")]
    series = pl.Series("status", ["AÇIK", "???", "PEND-REV", "???", None, "  "])
    values, report = map_labels(series, lookup)
    assert values.to_list() == ["OPEN", UNMAPPED, UNMAPPED, UNMAPPED, None, None]
    assert report.unmapped == (("???", 2), ("PEND-REV", 1))
    assert report.unmapped_rows == 3


def test_every_classified_field_of_a_concept_is_mapped() -> None:
    frame = pl.DataFrame(
        {
            "segment": ["Elementer", "HAYAT", "Sağlık", "BES"],
            "channel": ["Acente", "Bankasürans", "İnternet", "Broker"],
            "line": ["KASKO", "HAYAT", "SAĞLIK", "BES"],  # no classes: left as given
        }
    )
    mapped, reports = map_values(frame, "policies", DICTIONARY)
    assert mapped["segment"].to_list() == ["NON_LIFE", "LIFE", "HEALTH", "PENSION"]
    assert mapped["channel"].to_list() == ["AGENCY", "BANK", "DIGITAL", "BROKER"]
    assert mapped["line"].to_list() == frame["line"].to_list()
    assert [r.field for r in reports] == ["segment", "channel"]
