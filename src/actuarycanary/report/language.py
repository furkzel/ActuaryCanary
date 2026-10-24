"""The language of the report page (record 0224): English by default, Turkish on request.

Every label and sentence the report writes itself goes through `t` (or `th` where it holds
markup). Its argument is the English text, with `{name}` placeholders for what is filled in;
for Turkish the same text is looked up in `language.yaml`, which holds the English and the
Turkish text side by side. English is therefore the text in the code, Turkish the text in the
resource, and a test renders the page in both and checks that no label is left in English.

Text that is data or computed from the run, not a label of the report, is not translated:
the messages of data rules and diagnostics, the reasons of anomaly flags and the wording of
specifications. They are named in record 0224.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from pathlib import Path

import yaml
from markupsafe import Markup, escape

ENGLISH = "en"
TURKISH = "tr"
LANGUAGES = (ENGLISH, TURKISH)
RESOURCE = Path(__file__).parent / "language.yaml"
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_current: ContextVar[str] = ContextVar("report_language", default=ENGLISH)
_asked: ContextVar[set[str] | None] = ContextVar("report_texts_asked", default=None)


class LanguageError(ValueError):
    """The language resource is not valid."""


@cache
def catalogue() -> dict[str, str]:
    """English text -> Turkish text, from `language.yaml`."""
    raw = yaml.safe_load(RESOURCE.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for entry in raw["entries"]:
        english, turkish = " ".join(entry["en"].split()), " ".join(entry["tr"].split())
        if english in found:
            raise LanguageError(f"{english!r} is in the language resource twice")
        found[english] = turkish
    return found


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def current() -> str:
    return _current.get()


@contextmanager
def using(language: str) -> Iterator[None]:
    """The report is written in `language` inside the block."""
    if language not in LANGUAGES:
        raise LanguageError(f"unknown report language {language!r}; known: {', '.join(LANGUAGES)}")
    token = _current.set(language)
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def recording() -> Iterator[set[str]]:
    """The English texts asked for inside the block (for the test of the resource)."""
    seen: set[str] = set()
    token = _asked.set(seen)
    try:
        yield seen
    finally:
        _asked.reset(token)


def _translate(text: str) -> str:
    asked = _asked.get()
    if asked is not None:
        asked.add(text)
    if _current.get() == ENGLISH:
        return text
    return catalogue().get(text, text)


def _fill(text: str, values: dict[str, object]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], text)


def t(text: str, **values: object) -> str:
    """`text` (English, with `{name}` placeholders) in the language of the report."""
    return _fill(_translate(text), values)


def th(text: str, **values: object) -> Markup:
    """Like `t` for a text that holds markup; the values are escaped, the text is trusted."""
    return Markup(_fill(_translate(text), {k: escape(v) for k, v in values.items()}))


def untranslated(texts: set[str]) -> list[str]:
    """The English texts that have no Turkish text in the resource."""
    known = catalogue()
    return sorted(x for x in texts if x not in known)


def number_text(text: str) -> str:
    """A number written with English separators (1,234.5) in the separators of the language."""
    if _current.get() == ENGLISH:
        return text
    return text.translate({ord(","): ".", ord("."): ","})
