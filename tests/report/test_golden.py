"""Golden test of the report (decision 0074): every number and text behind the page of the tiny
baseline, as normalised JSON, equals the stored copy. The HTML bytes are not compared.

A deliberate change of numbers or wording is accepted by rewriting the copy:
`just golden`, then review the diff of tests/report/golden/baseline_tiny.json.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from actuarycanary.pipeline import RunResult

GOLDEN = Path(__file__).parent / "golden" / "baseline_tiny.json"
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


def golden_text(model: dict[str, Any]) -> str:
    return json.dumps(normalise(model), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def test_report_numbers_and_texts_equal_the_golden_copy(default_run: RunResult) -> None:
    text = golden_text(default_run.report_data)
    if os.environ.get(UPDATE) == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    stored = GOLDEN.read_text(encoding="utf-8")
    assert json.loads(text) == json.loads(stored), (
        f"the report differs from {GOLDEN.name}; if the change is intended, run `just golden`"
    )
