"""Golden test of the report (decision 0074): every number and text behind the page of the tiny
baseline, as normalised JSON, equals the stored copy. The HTML bytes are not compared. Output
files are held as SHA-256 and size; a file named in `TOLERANCE_FILES` of `golden_tolerance.py` would
be held as cells and compared with a tolerance (decision 0627; the list is empty since 0360).

A deliberate change of numbers or wording is accepted by rewriting the copy:
`just golden`, then review the diff of the two files in tests/report/golden/ (English and Turkish).
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from actuarycanary.pipeline import RunResult, RunSettings, run
from tests.report.golden_tolerance import differences, with_tables

GOLDEN_DIR = Path(__file__).parent / "golden"
# the English copy keeps its name; the Turkish run of the same data sits beside it (record 0366)
GOLDEN_FILES = {"en": "baseline_tiny.json", "tr": "baseline_tiny_tr.json"}
BASELINE_TINY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "baseline"
UPDATE = "ACTUARYCANARY_UPDATE_GOLDEN"
pytestmark = pytest.mark.integration


def normalise(value: Any) -> Any:
    """Floats to 10 significant digits, so the last bits of a platform do not count."""
    if isinstance(value, float):
        return float(f"{value:.10g}")
    if isinstance(value, dict):
        return {str(k): normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [normalise(v) for v in value]
    return value


def golden_text(model: dict[str, Any], folder: Path) -> str:
    """The golden JSON of a run: the report data, the tolerance files as cells."""
    model = with_tables(normalise(model), folder)
    return json.dumps(model, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.fixture(scope="module")
def runs(default_run: RunResult, tmp_path_factory: pytest.TempPathFactory, cache: Path):
    """The tiny baseline in both languages; the English one is the shared default run."""
    turkish = run(
        BASELINE_TINY,
        tmp_path_factory.mktemp("golden_tr"),
        RunSettings(language="tr"),
        cache_dir=cache,
    )
    return {"en": default_run, "tr": turkish}


@pytest.mark.parametrize("lang", sorted(GOLDEN_FILES))
def test_report_numbers_and_texts_equal_the_golden_copy(
    runs: dict[str, RunResult], lang: str
) -> None:
    result = runs[lang]
    golden = GOLDEN_DIR / GOLDEN_FILES[lang]
    text = golden_text(result.report_data, result.folder)
    if os.environ.get(UPDATE) == "1":
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(text, encoding="utf-8", newline="\n")
    stored = golden.read_text(encoding="utf-8")
    found = differences(json.loads(stored), json.loads(text))
    assert not found, (
        f"the {lang} report differs from {golden.name}; if the change is intended, "
        "run `just golden`:\n" + "\n".join(found)
    )


def test_run_ids_differ_by_language_and_each_is_stable(runs: dict[str, RunResult]) -> None:
    """The language is an input of the run id (record 0224); the first row of the cover in each
    golden copy holds the id."""
    assert runs["en"].run_id != runs["tr"].run_id
    for lang, name in GOLDEN_FILES.items():
        stored = json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))
        assert runs[lang].run_id == stored["cover"]["rows"][0]["value"], lang


def test_the_turkish_golden_holds_the_turkish_labels_and_no_english_page_labels() -> None:
    """The Turkish copy carries the Turkish sentences of the findings and the labels of the
    reserving, uncertainty, large-loss and survival parts, and none of their English labels
    (record 0366); the label test of test_language.py is the second line."""
    english = json.loads((GOLDEN_DIR / GOLDEN_FILES["en"]).read_text(encoding="utf-8"))
    turkish_text = (GOLDEN_DIR / GOLDEN_FILES["tr"]).read_text(encoding="utf-8")
    turkish = json.loads(turkish_text)
    found = {f["rule"]: f["text"] for f in turkish["key_findings"] + turkish["further_findings"]}
    plain = {f["rule"]: f["text"] for f in english["key_findings"] + english["further_findings"]}
    assert found.keys() == plain.keys() and found
    assert all(found[rule] != plain[rule] for rule in found)
    for label in (
        "Belirsizlik ve risk",
        "Rezerv tahmini (IBNR, seçilen)",
        "Büyük hasar payı",
        "Sağkalım analizi (Kaplan–Meier ve Cox)",
    ):
        assert f'"{label}"' in turkish_text, label
    for label in ("Uncertainty and risk", "Reserving", "Survival", "Large-loss", "Large loss"):
        assert label not in turkish_text, label
