"""The M08 page in both languages and the facts of KF44 to KF46 (RP01 1.5.0, record 0408).

Spec IDs proved: M08, RP01.
"""

import re
from pathlib import Path

import pytest

from actuarycanary.modules.reinsurance import reinsurance_run
from actuarycanary.modules.runner import AnalysisResult
from actuarycanary.report import language
from actuarycanary.report.facts import FactSet
from actuarycanary.report.reinsurance_section import add_reinsurance_facts, reinsurance_page
from tests.measures.reinsurance_book import book

TEMPLATE = Path(__file__).parents[2] / "src/actuarycanary/report/templates/reinsurance.html.j2"


def _spec(*ids: str) -> str:
    return ", ".join(ids)


def test_every_label_of_the_template_has_its_turkish_text() -> None:
    labels = set(re.findall(r'tr\("([^"]+)"', TEMPLATE.read_text(encoding="utf-8")))
    assert labels and labels <= set(language.catalogue())


def test_the_page_asks_only_for_texts_the_resource_has() -> None:
    inputs = book(qs_paid_d=100.0)
    run = reinsurance_run(inputs)
    with language.using("tr"), language.recording() as asked:
        body = reinsurance_page(AnalysisResult((), inputs), run, None, _spec, "TRY")
    assert body["available"] and body["differences"] == 1 and body["compared"] == 2
    assert [r["type"] for r in body["treaties"]] == ["Kota paylaşımı", "Hasar fazlası"]
    assert body["treaties"][1]["terms"] == "200 üzeri 250"
    assert language.untranslated(asked) == []


def test_facts_of_the_rules() -> None:
    facts: FactSet = {}
    add_reinsurance_facts(facts, reinsurance_run(book(qs_paid_d=100.0)))
    assert facts["reinsurance_differences"].value == 1
    assert facts["reinsurance_years_compared"].value == 2
    assert facts["reinsurance_differing_treaties"].value == "QS"
    assert facts["layers_exhausted"].value == 0  # B and D stay inside 250 xs 200
    assert facts["approximate_allocation_share"].value == pytest.approx(0.0)
    quiet: FactSet = {}
    add_reinsurance_facts(quiet, None)
    assert quiet == {}
