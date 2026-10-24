"""The report in English and in Turkish (record 0224): the resource is complete and consistent,
every rule of RP01 has a Turkish sentence, numbers follow the language, and no label of the
Turkish page is left in English. Text that is data or computed from the run (messages of data
rules, diagnostics and anomaly flags, the wording of specifications) is not a label and is
checked to be exactly that."""

import html
import re
from pathlib import Path

import pytest

from actuarycanary.pipeline import RunResult, RunSettings, run
from actuarycanary.report import language, numbers
from actuarycanary.report.findings import Fact, facts_named, sentence
from actuarycanary.spec.loader import load_specs

BASELINE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"
SPECS = load_specs()
# the same word in both languages
SAME = {
    "NET",
    "Cape Cod",
    "Bornhuetter–Ferguson",
    "bornhuetter ferguson",
    "cape cod",
    "{label}: %{x:,.0f} {currency}<extra></extra>",
    "segment",
}


def test_every_entry_keeps_its_placeholders_and_differs_from_the_english() -> None:
    entries = language.catalogue()
    assert len(entries) > 300
    for english, turkish in entries.items():
        assert language.placeholders(english) == language.placeholders(turkish), english
        assert turkish.strip() == turkish and turkish, english
        if turkish == english:
            assert english in SAME, english


def test_english_is_the_text_in_the_code_and_turkish_the_text_in_the_resource() -> None:
    assert language.t("Key findings") == "Key findings"
    with language.using("tr"):
        assert language.t("Key findings") == "Temel bulgular"
        assert language.t("Reserving: {name}", name="X") == "Rezervleme: X"
        assert language.t("a sentence nobody translated") == "a sentence nobody translated"
    assert str(language.th("<b>{x}</b>", x="<i>")) == "<b>&lt;i&gt;</b>"
    with pytest.raises(language.LanguageError), language.using("de"):
        pass


def test_numbers_use_the_separators_of_the_language() -> None:
    assert numbers.amount(1234567.4) == "1,234,567"
    assert numbers.ratio(0.1234) == "12.3%"
    assert numbers.factor(1.05) == "1.050"
    assert numbers.change_ratio(0.052) == "+5.2%"
    assert numbers.change_points(-0.012) == "−1.2 pts"
    with language.using("tr"):
        assert numbers.amount(1234567.4) == "1.234.567"
        assert numbers.ratio(0.1234) == "%12,3"
        assert numbers.ratio(-0.0451) == "-%4,5"
        assert numbers.factor(1.05) == "1,050"
        assert numbers.change_ratio(0.052) == "+%5,2"
        assert numbers.change_ratio(-0.04) == "−%4,0"
        assert numbers.change_points(-0.012) == "−1,2 puan"
        assert numbers.change_amount(0) == "0"
        assert numbers.amount(None) == numbers.EMPTY


def test_every_rule_of_rp01_has_a_turkish_sentence_with_the_same_facts() -> None:
    rules = SPECS.finding_rules.rules
    assert len(rules) == 23 and SPECS.finding_rules.version == "1.1.0"
    placeholder = re.compile(r"\{([a-z][a-z0-9_]*)\}")
    for rule in rules:
        assert set(placeholder.findall(rule.template)) == set(placeholder.findall(rule.template_tr))
        assert rule.title_tr and rule.title_tr != rule.title
        assert facts_named(rule)


def test_a_rule_writes_its_sentence_in_the_language_of_the_report() -> None:
    rule = next(r for r in SPECS.finding_rules.rules if r.id == "KF06")
    facts = {
        "segment": Fact("NON_LIFE", "text"),
        "premium_change": Fact(0.412, "ratio"),
        "written_premium": Fact(45783739.0, "amount"),
        "currency": Fact("TRY", "text"),
        "premium_period": Fact("2025", "text"),
        "premium_previous_period": Fact("2024", "text"),
    }
    assert sentence(rule, facts) == (
        "NON_LIFE: written premium grew by 41.2% to 45,783,739 TRY in 2025 against 2024."
    )
    with language.using("tr"):
        assert sentence(rule, facts) == (
            "NON_LIFE: yazılan prim 2024 dönemine göre %41,2 artarak 2025 döneminde "
            "45.783.739 TRY oldu."
        )


@pytest.fixture(scope="module")
def turkish(tmp_path_factory: pytest.TempPathFactory, cache: Path):
    with language.recording() as asked:
        result = run(
            BASELINE,
            tmp_path_factory.mktemp("tr"),
            RunSettings(language="tr"),
            cache_dir=cache,
        )
    return result, asked


def _text_nodes(page: str) -> list[str]:
    body = page.split("<main>", 1)[1].split("</main>", 1)[0]
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    parts = re.split(r"<[^>]+>", body)
    return [" ".join(html.unescape(p).split()) for p in parts if p.strip()]


def _content(result: RunResult) -> list[str]:
    """Text that is data or computed from the run: messages of data rules and of the quality
    report, diagnostics, anomaly flags, notes and reasons of measures and modules, and the
    wording of the specifications."""
    found: list[str] = [f.message for f in result.findings]
    found += [f.message for f in result.quality.findings]
    found += [why for _, why in result.quality.not_evaluated]
    for rule in SPECS.data.values():
        found += [r.rule for r in rule.validation]
    for method in SPECS.methods.values():
        found += [method.definition, *(a.statement for a in method.assumptions)]
    for group in result.reserving.groups:
        found += [d.item.message for d in group.diagnostics]
        found += [str(getattr(m, "reason", "")) for m in group.mack.values()]
        found += list(getattr(group.selection, "why", ()))
    found += result.anomalies.flags["reason"].to_list()
    found += list(result.anomalies.reasons)
    for outcome in result.analysis.modules:
        found += list(outcome.reasons)
        for measure in outcome.measures:
            found += [measure.reason, *measure.notes]
    return [" ".join(x.split()) for x in found if x]


@pytest.mark.slow
def test_the_turkish_report_asks_only_for_texts_the_resource_has(turkish) -> None:
    result, asked = turkish
    missing = language.untranslated(asked)
    others = [x for x in missing if x not in " ".join(_content(result))]
    # what is left over is a module reason or a note built from the run, not a label
    assert not [x for x in others if not re.match(r"^(MT0\d|MT10|AE01|CL\d\d|RS0\d|PR0\d)", x)]
    assert result.report_data["language"] == "tr"
    assert 'lang="tr"' in result.report.read_text(encoding="utf-8")


ENGLISH_WORDS = re.compile(r"\b(the|of|and|is|not|for|with|are|by|on|in|to|at|from)\b")


@pytest.mark.slow
def test_no_label_of_the_turkish_report_is_left_in_english(turkish, default_run: RunResult) -> None:
    result, _ = turkish
    english = set(_text_nodes(default_run.report.read_text(encoding="utf-8")))
    content = " ".join(_content(result))
    leaks = []
    for node in dict.fromkeys(_text_nodes(result.report.read_text(encoding="utf-8"))):
        if node not in english or not ENGLISH_WORDS.search(node):
            continue  # translated, or not a sentence in English at all (an id, a number, a name)
        parts = [*node.split("; "), node.split(": ", 1)[-1]]  # "2022: why" is origin and text
        if node in content or any(part in content for part in parts):
            continue  # data or computed text, not a label
        leaks.append(node)
    assert not leaks, chr(10).join(leaks)
    # and the labels that every page has are the Turkish ones
    page = result.report.read_text(encoding="utf-8")
    for label in ("Temel bulgular", "Bir bakışta", "Rezervleme", "Yeniden üretilebilirlik eki"):
        assert label in page
    for label in ("Key findings", "At a glance", "Case reserve", "Written premium"):
        assert f">{label}<" not in page


@pytest.mark.slow
def test_the_language_enters_the_run_id_and_the_other_outputs_stay_english(
    turkish, default_run: RunResult
) -> None:
    result, _ = turkish
    assert result.run_id != default_run.run_id
    for name in ("measures.csv", "anomalies.csv", "diagnostics.csv"):
        assert (result.folder / name).read_bytes() == (default_run.folder / name).read_bytes()
    manifest = (result.folder / "manifest.json").read_text(encoding="utf-8")
    assert '"language": "tr"' in manifest
    with pytest.raises(ValueError, match="report language"):
        RunSettings(language="de")


@pytest.mark.slow
def test_the_charts_of_the_turkish_report_use_decimal_commas(turkish) -> None:
    result, _ = turkish
    figures = result.report_data["figures"]
    layouts = [f["layout"] for f in figures.values()]
    assert layouts and all(x.get("separators") == ",." for x in layouts)
    titles = {f["layout"]["title"]["text"] for f in figures.values()}
    assert any(x.startswith("Birikimli ödenen") for x in titles)
