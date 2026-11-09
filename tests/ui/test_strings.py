"""The strings file: a missing Turkish text is a failing test (record 0705)."""

import re
from pathlib import Path

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.pipeline import RunSettings  # noqa: F401  (the stage test reads its source)
from actuarycanary.recognition.columns import Layer
from actuarycanary.recognition.tables import Source
from actuarycanary.ui import server, settings, strings
from actuarycanary.ui.runner import STAGES

UI = Path(server.__file__).parent
PIPELINE = Path(__file__).parents[2] / "src" / "actuarycanary" / "pipeline.py"


def test_every_id_has_both_texts_and_the_same_placeholders() -> None:
    for key, texts in strings.entries().items():
        assert texts["en"], key
        assert texts["tr"], f"{key} has no Turkish text"
        assert strings.placeholders(texts["en"]) == strings.placeholders(texts["tr"]), key


def test_a_turkish_text_is_not_the_english_one_unless_it_is_a_name_or_a_symbol() -> None:
    same = {k for k, t in strings.entries().items() if t["en"] == t["tr"]}
    names = {
        "app.title", "opt.basis.net", "opt.value.nominal", "result.col_ibnr", "browser.up",
    }  # fmt: skip
    assert same <= names, sorted(same - names)


def test_turkish_texts_use_turkish_letters_where_the_language_needs_them() -> None:
    # a cheap guard against English text pasted into the Turkish column
    for key in ("start.intro", "mapping.intro", "run.cancel_hint", "set.lang_hint"):
        assert re.search(r"[çğıöşüÇĞİÖŞÜ]", strings.entries()[key]["tr"]), key


def _ids_in_page() -> set[str]:
    template = (UI / "templates" / "index.html.j2").read_text(encoding="utf-8")
    script = (UI / "static" / "app.js").read_text(encoding="utf-8")
    found = set(re.findall(r"""\bs\(["']([a-z0-9_.-]+)["']""", template))
    found |= set(re.findall(r"""\bS\(["']([a-z0-9_.-]+)["']""", script))
    found |= set(re.findall(r'"((?:mapping|findings|result|past|run|start)\.[a-z_]+)"', script))
    return {key for key in found if not key.endswith(".")}  # "layer." etc. are built from a value


def test_every_id_the_page_asks_for_is_in_the_file() -> None:
    missing = sorted(_ids_in_page() - set(strings.entries()))
    assert not missing, missing


def test_every_id_in_the_file_is_asked_for_by_the_page_or_the_server() -> None:
    families = (
        "stage.", "opt.", "layer.", "state.", "severity.", "error.", "run.state.", "run.stage.",
    )  # fmt: skip
    unused = sorted(
        k for k in strings.entries() if k not in _ids_in_page() and not k.startswith(families)
    )
    assert not unused, unused


def test_the_families_built_from_a_value_cover_every_value() -> None:
    expected = (
        {f"opt.basis.{b}" for b in settings.BASES}
        | {f"opt.value.{v}" for v in settings.VALUES}
        | {f"opt.axis.{a}" for a in settings.ORIGIN_AXES}
        | {f"opt.period.{p}" for p in settings.PERIODS}
        | {f"opt.view.{c}" for c in settings.CURRENCY_VIEWS}
        | {f"layer.{layer.value}" for layer in Layer}
        | {f"stage.{i}" for i in range(len(STAGES))}
        | {f"severity.{s}" for s in ("BLOCKING", "WARNING", "INFO")}
        | {f"run.state.{s}" for s in ("running", "done", "failed", "cancelled")}
        | {f"run.stage.{s}" for s in ("done", "running", "failed", "pending")}
        | {f"state.{s}" for s in ("canonical", "saved", "proposed", "skipped", "not_recognised")}
    )
    assert not expected - set(strings.entries()), sorted(expected - set(strings.entries()))
    assert ReinsuranceBasis and Source  # the enums the families follow


def test_every_error_code_the_server_raises_has_a_text() -> None:
    source = "".join(p.read_text(encoding="utf-8") for p in (UI / "server.py", UI / "scan.py"))
    codes = set(re.findall(r'(?:ApiError\([^"]*?|ScanError\()"([a-z_]+)"', source))
    assert codes, "no error codes found"
    missing = sorted(c for c in codes if f"error.{c}" not in strings.entries())
    assert not missing, missing
    assert "error.server_gone" in strings.entries()  # raised by the page itself


def test_the_stage_list_is_what_the_pipeline_reports() -> None:
    reported = re.findall(r'step\("([^"]+)"\)', PIPELINE.read_text(encoding="utf-8"))
    assert list(STAGES) == reported
    english = [strings.text("en", f"stage.{i}") for i in range(len(STAGES))]
    assert english == list(STAGES)


def test_unknown_language_is_not_a_language() -> None:
    with pytest.raises(KeyError):
        strings.text("de", "app.title")
