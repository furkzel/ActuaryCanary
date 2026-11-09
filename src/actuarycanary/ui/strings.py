"""The texts of the interface, English and Turkish side by side in `strings.yaml` (record 0705).

Every text of every screen has an id, an English text and a Turkish text; `{name}` marks what is
filled in and must appear in both. A test fails for an id without a Turkish text, for a
placeholder missing from one language, and for an id the page asks for but the file lacks. Text
that comes from the pipeline (data messages, errors, stage names the interface does not know) is
shown as the pipeline wrote it, as the terminal shows it.
"""

import re
from functools import cache
from pathlib import Path

import yaml

RESOURCE = Path(__file__).parent / "strings.yaml"
ENGLISH, TURKISH = "en", "tr"
LANGUAGES = (ENGLISH, TURKISH)
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class StringsError(ValueError):
    """The strings file is not valid."""


@cache
def entries() -> dict[str, dict[str, str]]:
    """id -> {"en": text, "tr": text}."""
    raw = yaml.safe_load(RESOURCE.read_text(encoding="utf-8"))
    found: dict[str, dict[str, str]] = {}
    for entry in raw["entries"]:
        key = entry["id"]
        if key in found:
            raise StringsError(f"{key!r} is in the strings file twice")
        found[key] = {lang: " ".join(str(entry.get(lang, "")).split()) for lang in LANGUAGES}
    return found


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def table(language: str) -> dict[str, str]:
    """id -> text for one language."""
    return {key: texts[language] for key, texts in entries().items()}


def fill(text: str, values: dict[str, object]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], text)


def text(language: str, key: str, **values: object) -> str:
    return fill(entries()[key][language], values)
