"""The messiness layer: turns clean canonical tables into the files an insurer might send.

Renamed, misspelt and Turkish headers (taken from the alias dictionary AL01), reordered
columns, title rows above the header, dates as text in several formats, status and type
labels given as dictionary aliases (AL02), and personal-data columns that must be dropped.
Every change is recorded, so a recogniser can be scored against the truth.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl
import yaml

from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.scenario import Scenario

DATE_FORMATS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d")
SHEET_NAMES = {
    "claim_valuations": ("claim_valuations", "Sheet1", "Sayfa1", "Hasar"),
    "claims": ("claims", "Sheet1", "Sayfa1", "Hasar Listesi"),
    "policies": ("policies", "Sheet1", "Sayfa1", "Poliçeler"),
    "premiums": ("premiums", "Sheet1", "Sayfa1", "Prim"),
    "expenses": ("expenses", "Sheet1", "Sayfa1", "Giderler"),
    "market": ("market", "Sheet1", "Sayfa1", "Piyasa"),
}
MARKET_SHEETS = {"fx": ("fx", "Kurlar", "Döviz"), "cpi": ("cpi", "Enflasyon", "TÜFE")}
FIRST_NAMES = (
    "Ayşe",
    "Mehmet",
    "Fatma",
    "Ali",
    "Zeynep",
    "Mustafa",
    "Elif",
    "Hasan",
    "Emine",
    "Ahmet",
    "Selin",
    "Burak",
)
LAST_NAMES = (
    "Yılmaz",
    "Kaya",
    "Demir",
    "Çelik",
    "Şahin",
    "Yıldız",
    "Aydın",
    "Öztürk",
    "Arslan",
    "Doğan",
    "Kılıç",
    "Aslan",
)
TITLES = {
    "claim_valuations": "Hasar Değerleme Raporu",
    "claims": "Hasar Listesi",
    "policies": "Poliçe Listesi",
    "premiums": "Prim Hareketleri",
    "expenses": "Gider Dökümü",
    "market": "Piyasa Verileri",
}


@dataclass
class SheetPlan:
    """One worksheet as it will be written: title rows, a header and columns of cell values."""

    name: str
    title_rows: list[list[str]]
    headers: list[str]
    columns: list[list[Any]]

    @property
    def header_row(self) -> int:
        """1-based worksheet row of the header."""
        return len(self.title_rows) + 1

    @property
    def n_rows(self) -> int:
        return len(self.columns[0]) if self.columns else 0


@dataclass
class MessLog:
    columns: list[dict[str, str]] = field(default_factory=list)
    values: list[dict[str, str]] = field(default_factory=list)
    dates: list[dict[str, str]] = field(default_factory=list)


class Dictionaries:
    """The alias dictionaries of spec/aliases/ in a lookup form."""

    def __init__(self) -> None:
        root = find_spec_root() / "aliases"
        columns = yaml.safe_load((root / "columns.yaml").read_text(encoding="utf-8"))
        values = yaml.safe_load((root / "values.yaml").read_text(encoding="utf-8"))
        self.columns: dict[tuple[str, str], list[str]] = {}
        for entry in columns["columns"]:
            for concept in entry["concepts"]:
                self.columns[(concept, entry["field"])] = list(entry["aliases"])
        self.values: dict[tuple[str, str], dict[str, list[str]]] = {}
        for entry in values["values"]:
            for concept in entry["concepts"]:
                self.values[(concept, entry["field"])] = {
                    k: list(v) for k, v in entry["classes"].items()
                }


def misspell(text: str, rng: np.random.Generator) -> str:
    """One typing slip: a missing, doubled or swapped letter (never the first letter)."""
    letters = [i for i, ch in enumerate(text) if ch.isalpha() and i > 0]
    if len(letters) < 3:
        return text
    i = letters[int(rng.integers(len(letters)))]
    operation = int(rng.integers(3))
    if operation == 0:
        slipped = text[:i] + text[i + 1 :]
    elif operation == 1:
        slipped = text[:i] + text[i] + text[i:]
    elif i >= 2 and text[i - 1].isalpha() and text[i] != text[i - 1]:
        slipped = text[: i - 1] + text[i] + text[i - 1] + text[i + 1 :]
    else:
        slipped = text[:i] + text[i + 1 :]
    return slipped if slipped != text else text[:i] + text[i + 1 :]


def _header_text(alias: str, rng: np.random.Generator) -> str:
    """The alias as typed in a sheet: as is, joined with underscores, or with a trailing space."""
    style = int(rng.integers(3))
    if style == 0:
        return alias
    if style == 1:
        return alias.replace(" ", "_")
    return alias + " "


def _fake_personal(kind: str, n: int, rng: np.random.Generator) -> list[str]:
    if kind == "name":
        first = rng.integers(len(FIRST_NAMES), size=n)
        last = rng.integers(len(LAST_NAMES), size=n)
        return [f"{FIRST_NAMES[a]} {LAST_NAMES[b]}" for a, b in zip(first, last, strict=True)]
    if kind == "national_id_11_digits":
        digits = rng.integers(0, 10, size=(n, 10))
        return [
            f"{1 + int(row[0]) % 9}{''.join(str(int(d)) for d in row[1:])}{int(rng.integers(10))}"
            for row in digits
        ]
    return [f"{int(v):07d}" for v in rng.integers(1, 10**7, size=n)]


def _cells(series: pl.Series) -> list[Any]:
    return series.to_list()


def layout_sheet(
    scenario: Scenario,
    dictionaries: Dictionaries,
    streams: Streams,
    feed: str,
    sheet_key: str,
    frame: pl.DataFrame,
    log: MessLog,
    sheet_name: str,
) -> SheetPlan:
    """Lay one clean table out as a worksheet, applying the scenario's mess settings."""
    mess = scenario.messiness
    rng = streams.get("messy", feed, sheet_key)
    n = frame.height
    names = list(frame.columns)
    headers: list[str] = []
    kinds: list[str] = []
    for name in names:
        aliases = dictionaries.columns.get((feed, name), [])
        if (
            mess.headers.style == "canonical"
            or not aliases
            or rng.random() < mess.headers.canonical_share
        ):
            text, kind = name, "canonical"
        else:
            text, kind = _header_text(aliases[int(rng.integers(len(aliases)))], rng), "alias"
        if mess.headers.misspell_share > 0 and rng.random() < mess.headers.misspell_share:
            text, kind = misspell(text, rng), "misspelt"
        headers.append(text)
        kinds.append(kind)

    columns: list[list[Any]] = []
    for name, text, kind in zip(names, headers, kinds, strict=True):
        series = frame[name]
        cells = _cells(series)
        classes = dictionaries.values.get((feed, name))
        if classes and mess.value_labels.translate_share > 0:
            cells = _translate(
                cells, classes, mess.value_labels.translate_share, rng, log, feed, name
            )
        if series.dtype == pl.Date and mess.date_formats.text_share > 0:
            cells = _dates_as_text(cells, mess.date_formats.text_share, rng, log, feed, name)
        columns.append(cells)
        log.columns.append(
            {"file": feed, "sheet": sheet_name, "header": text, "field": name, "kind": kind}
        )

    if mess.personal_data and feed in ("claims", "policies"):
        for column in scenario.personal_data_columns:
            headers.append(column.name)
            columns.append(_fake_personal(column.kind, n, rng))
            log.columns.append(
                {
                    "file": feed,
                    "sheet": sheet_name,
                    "header": column.name,
                    "field": "",
                    "kind": f"personal:{column.kind}",
                }
            )

    if mess.headers.style == "aliases":
        order = rng.permutation(len(headers))
        headers = [headers[i] for i in order]
        columns = [columns[i] for i in order]

    n_title = (
        int(rng.integers(mess.title_rows.min, mess.title_rows.max + 1))
        if mess.title_rows.max > 0
        else 0
    )
    cut_off = scenario.meta.valuation.last
    lines = [
        f"{scenario.entities[0].name} - {TITLES[feed]}",
        f"Rapor tarihi: {cut_off:%d.%m.%Y}",
        "Tutarlar orijinal para birimi cinsindendir",
    ]
    title_rows = [[lines[i]] if i < len(lines) else [] for i in range(n_title)]
    return SheetPlan(sheet_name, title_rows, headers, columns)


def _translate(
    cells: list[Any],
    classes: dict[str, list[str]],
    share: float,
    rng: np.random.Generator,
    log: MessLog,
    feed: str,
    field_name: str,
) -> list[Any]:
    seen: set[tuple[str, str]] = set()
    chosen = rng.random(len(cells)) < share
    pick = rng.random(len(cells))
    out = list(cells)
    for i in np.flatnonzero(chosen):
        label = cells[i]
        aliases = classes.get(label) if isinstance(label, str) else None
        if not aliases:
            continue
        alias = aliases[int(pick[i] * len(aliases))]
        out[i] = alias
        if (alias, label) not in seen:
            seen.add((alias, label))
            log.values.append({"file": feed, "field": field_name, "label": alias, "class": label})
    return out


def _dates_as_text(
    cells: list[Any],
    share: float,
    rng: np.random.Generator,
    log: MessLog,
    feed: str,
    field_name: str,
) -> list[Any]:
    fmt = DATE_FORMATS[int(rng.integers(len(DATE_FORMATS)))]
    chosen = rng.random(len(cells)) < share
    out = list(cells)
    for i in np.flatnonzero(chosen):
        if isinstance(cells[i], date):
            out[i] = cells[i].strftime(fmt)
    log.dates.append(
        {"file": feed, "field": field_name, "text_format": fmt, "text_share": f"{share:g}"}
    )
    return out


def sheet_name_for(feed: str, sheet_key: str, scenario: Scenario, streams: Streams) -> str:
    if scenario.messiness.headers.style == "canonical":
        return sheet_key if feed == "market" else feed
    rng = streams.get("messy", "sheet", feed, sheet_key)
    options = MARKET_SHEETS[sheet_key] if feed == "market" else SHEET_NAMES[feed]
    return options[int(rng.integers(len(options)))]
