"""Concept detection (blueprint 6.2): scored by fields and grain; names are only a hint."""

import pytest

from actuarycanary.recognition.concepts import best_concept, score_concepts
from actuarycanary.recognition.tables import Source, recognise_table
from actuarycanary.recognition.value_profile import profile_values
from tests.recognition.build import DICTIONARY, table, valuations


def _scores(columns: dict, names: tuple[str, ...] = ("input", "Sheet1")):
    raw = table(columns)
    profiles = {h: profile_values(raw.frame[h]) for h in raw.headers}
    return score_concepts(raw.frame, raw.headers, names, DICTIONARY, profiles)


def test_claim_valuations_are_found_with_scores_for_every_concept() -> None:
    scores = _scores(valuations(claim_id="HASAR NO", paid_to_date="ÖDENEN"))
    assert scores[0].concept == "claim_valuations"
    assert scores[0].complete
    assert scores[0].grain.startswith("keys unique")
    assert {s.concept for s in scores} == set(DICTIONARY.concepts)
    assert scores[0].score > scores[1].score


def test_file_name_is_a_hint_never_a_rule() -> None:
    columns = valuations()
    misleading = _scores(columns, names=("claims", "claims"))
    assert misleading[0].concept == "claim_valuations"
    assert next(s for s in misleading if s.concept == "claims").name_hint


def test_name_hint_only_breaks_ties() -> None:
    plain = _scores(valuations())
    hinted = _scores(valuations(), names=("claim_valuations", "Sheet1"))
    assert hinted[0].score - plain[0].score == pytest.approx(0.05)


def test_grain_failure_lowers_the_score() -> None:
    columns = valuations()
    columns["claim_id"] = ["0001"] * 4
    columns["valuation_date"] = ["2024-01-31"] * 4
    scores = _scores(columns)
    assert scores[0].grain.startswith("keys not unique")


def test_an_unrelated_sheet_has_no_concept() -> None:
    scores = _scores({"Açıklama": ["a", "b"], "Not": ["c", "d"]})
    assert best_concept(scores) is None
    rec = recognise_table(table({"Açıklama": ["a", "b"], "Not": ["c", "d"]}), "x.xlsx", DICTIONARY)
    assert rec.concept is None


def test_canonical_layout_needs_no_confirmation() -> None:
    assert recognise_table(table(valuations()), "x.xlsx", DICTIONARY).source is Source.CANONICAL
    renamed = recognise_table(table(valuations(status="DURUM")), "x.xlsx", DICTIONARY)
    assert renamed.source is Source.AUTOMATIC
