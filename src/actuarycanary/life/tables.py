"""Reference tables of the life studies (records 0443, 0444): mortality, disability, lapse and
surrender rates read from the folder `reference_tables/` inside the data folder.

Format. One CSV file per table with a key column, `age` (whole years) or `policy_year` (1 for
the first year), a `rate` column and, optionally, `rate_kind` (`q`, `mu` or `m`, one value for
the whole file), `sex` (FEMALE or MALE), `select_duration` and `product` (further keys, for
example a lapse table by product and policy year). Beside it a sidecar `<file stem>.yaml` holds
`name`, `decrement` (DEATH, DISABILITY, LAPSE or SURRENDER), `source`, `licence`, optionally
`description`, and `rate_kind` when the CSV has no such column.

Checks. The sidecar is present and complete; the key is one of age (0 to 120) and policy_year
(1 or more), whole numbers; every rate is present, 0 <= q < 1, mu and m >= 0; keys are unique;
no age or policy year is missing inside the range of a group (sex, select duration, product).
A table that fails any check is not used and is listed with its reasons. The SHA-256 of the CSV
and of the sidecar of every table used enter the manifest and the run id.

No table ships with the package (record 0444): only the user's files are read.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

FOLDER = "reference_tables"
DECREMENTS = ("DEATH", "DISABILITY", "LAPSE", "SURRENDER")
RATE_KINDS = ("q", "mu", "m")
KEYS = ("age", "policy_year")
GROUPS = ("sex", "select_duration", "product")  # further keys a table may carry
SEXES = ("FEMALE", "MALE")
SIDECAR_REQUIRED = ("name", "decrement", "source", "licence")
MAX_AGE = 120


@dataclass(frozen=True)
class ReferenceTable:
    file: str  # the CSV's name inside reference_tables/
    name: str
    decrement: str
    key: str  # age or policy_year
    rate_kind: str  # q, mu or m, as given
    source: str
    licence: str
    description: str
    sha256: str  # of the CSV
    sidecar_sha256: str
    frame: pl.DataFrame = field(repr=False)  # key, the group columns present, rate

    @property
    def rows(self) -> int:
        return self.frame.height

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(g for g in GROUPS if g in self.frame.columns)

    def force(self) -> pl.Series:
        """The rate as a constant force over the year (CV11): mu = -ln(1 - q); m is taken as
        mu (a central rate over the year equals the constant force that gives it)."""
        return to_force(self.frame["rate"], self.rate_kind)

    def probability(self) -> pl.Series:
        """The rate as a probability over the year: q = 1 - exp(-mu)."""
        return to_probability(self.frame["rate"], self.rate_kind)

    def manifest_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": f"{FOLDER}/{self.file}",
            "sha256": self.sha256,
            "sidecar_sha256": self.sidecar_sha256,
            "rows": self.rows,
            "decrement": self.decrement,
            "key": self.key,
            "rate_kind": self.rate_kind,
            "source": self.source,
            "licence": self.licence,
        }


@dataclass(frozen=True)
class TablesRead:
    used: tuple[ReferenceTable, ...]
    not_used: tuple[tuple[str, str], ...]  # (file, every reason, joined)

    @property
    def found(self) -> bool:
        return bool(self.used or self.not_used)

    def manifest_record(self) -> dict[str, Any]:
        return {
            "used": [t.manifest_record() for t in self.used],
            "not_used": [{"file": f"{FOLDER}/{f}", "reasons": r} for f, r in self.not_used],
        }

    def run_id_record(self) -> dict[str, Any]:
        """What the figures rest on: the files used and their content."""
        return {
            "concept": FOLDER,
            "tables": [[t.file, t.sha256, t.sidecar_sha256] for t in self.used],
        }


def to_force(rate: pl.Series, kind: str) -> pl.Series:
    if kind == "q":
        return pl.Series(rate.name, -np.log1p(-rate.to_numpy()))
    return rate


def to_probability(rate: pl.Series, kind: str) -> pl.Series:
    if kind == "q":
        return rate
    return pl.Series(rate.name, -np.expm1(-rate.to_numpy()))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar(path: Path) -> tuple[dict[str, Any] | None, str, list[str]]:
    sidecar = path.with_suffix(".yaml")
    if not sidecar.is_file():
        return None, "", [f"no sidecar {sidecar.name} (name, decrement, source, licence)"]
    data = sidecar.read_bytes()
    try:
        meta = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        return None, _sha256(data), [f"{sidecar.name} is not readable YAML: {error}"]
    if not isinstance(meta, dict):
        return None, _sha256(data), [f"{sidecar.name} is not a mapping of keys to values"]
    problems = [
        f"{sidecar.name} has no {k}" for k in SIDECAR_REQUIRED if not str(meta.get(k) or "").strip()
    ]
    decrement = str(meta.get("decrement") or "").strip().upper()
    if decrement and decrement not in DECREMENTS:
        problems.append(f"decrement {decrement} is not one of {', '.join(DECREMENTS)}")
    return meta, _sha256(data), problems


def _whole(column: pl.Series) -> bool:
    values = column.cast(pl.Float64, strict=False)
    return values.null_count() == 0 and bool((values == values.round(0)).all())


def _check_frame(
    frame: pl.DataFrame, meta: dict[str, Any]
) -> tuple[pl.DataFrame, str, str, list[str]]:
    """(frame of key, groups and rate; key; rate kind; problems)."""
    problems: list[str] = []
    keys = [k for k in KEYS if k in frame.columns]
    if len(keys) != 1:
        problems.append("the table needs exactly one key column, age or policy_year")
        return frame, "", "", problems
    key = keys[0]
    if "rate" not in frame.columns:
        return frame, key, "", [*problems, "no rate column"]
    kinds = (
        frame["rate_kind"].cast(pl.String).str.strip_chars().str.to_lowercase().unique().to_list()
        if "rate_kind" in frame.columns
        else [str(meta.get("rate_kind") or "").strip().lower()]
    )
    kind = kinds[0] if len(kinds) == 1 else ""
    if len(kinds) != 1:
        problems.append("rate_kind must be one value for the whole file")
    elif kind not in RATE_KINDS:
        problems.append(f"rate_kind {kind or '(none)'} is not q, mu or m")
    if not _whole(frame[key]):
        problems.append(f"{key} has empty or fractional values")
        return frame, key, kind, problems
    groups = [g for g in GROUPS if g in frame.columns]
    out = frame.select(
        pl.col(key).cast(pl.Float64).cast(pl.Int64),
        *(pl.col(g).cast(pl.String).str.strip_chars() for g in groups),
        pl.col("rate").cast(pl.Float64, strict=False),
    )
    low_key = 0 if key == "age" else 1
    if (out[key] < low_key).any() or (key == "age" and (out[key] > MAX_AGE).any()):
        problems.append(f"{key} outside {low_key} to {MAX_AGE if key == 'age' else 'any'}")
    if "sex" in groups and not out["sex"].is_in(SEXES).all():
        problems.append("sex is not FEMALE or MALE")
    rate = out["rate"]
    if rate.null_count():
        problems.append(f"{rate.null_count()} rates are empty or not numbers")
    finite = rate.drop_nulls()
    if kind == "q" and ((finite < 0) | (finite >= 1)).any():
        problems.append("a q is outside 0 <= q < 1")
    if kind in ("mu", "m") and ((finite < 0) | finite.is_nan()).any():
        problems.append(f"a {kind} is negative")
    if out.select([key, *groups]).is_duplicated().any():
        problems.append(f"{' and '.join([key, *groups])} repeat")
    else:
        span = (pl.col(key).min().alias("lo"), pl.col(key).max().alias("hi"), pl.len())
        spans = (out.group_by(groups).agg(*span) if groups else out.select(*span)).filter(
            pl.col("hi") - pl.col("lo") + 1 != pl.col("len")
        )
        if spans.height:
            problems.append(f"{key} has gaps inside the table's range")
    return out, key, kind, problems


def read_table(path: Path) -> tuple[ReferenceTable | None, list[str]]:
    """The table of one CSV file and its sidecar, or None and every reason it is not used."""
    meta, sidecar_sha, problems = _sidecar(path)
    data = path.read_bytes()
    try:
        frame = pl.read_csv(data, infer_schema_length=0)  # every column as text first
    except pl.exceptions.PolarsError as error:
        return None, [*problems, f"not a readable CSV: {error}"]
    frame = frame.rename({c: c.strip().lower() for c in frame.columns})
    if frame.height == 0:
        return None, [*problems, "the table has no rows"]
    checked, key, kind, more = _check_frame(frame, meta or {})
    problems += more
    if problems or meta is None:
        return None, problems
    table = ReferenceTable(
        file=path.name,
        name=str(meta["name"]).strip(),
        decrement=str(meta["decrement"]).strip().upper(),
        key=key,
        rate_kind=kind,
        source=str(meta["source"]).strip(),
        licence=str(meta["licence"]).strip(),
        description=str(meta.get("description") or "").strip(),
        sha256=_sha256(data),
        sidecar_sha256=sidecar_sha,
        frame=checked,
    )
    return table, []


def read_tables(data_folder: Path) -> TablesRead:
    """Every CSV of `data_folder/reference_tables/`, by name: used or listed with its reasons."""
    folder = data_folder / FOLDER
    if not folder.is_dir():
        return TablesRead((), ())
    used: list[ReferenceTable] = []
    not_used: list[tuple[str, str]] = []
    for path in sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"):
        table, problems = read_table(path)
        if table is None:
            not_used.append((path.name, "; ".join(problems)))
        else:
            used.append(table)
    return TablesRead(tuple(used), tuple(not_used))
