"""Assumptions register (blueprint section 12): every judgement a method uses, with its value,
the default it replaces, who chose it, when and why.

User entries come in; the entries in force come out. An entry in force is either a user
entry or the platform default, whose `who` is DEFAULT_WHO. Methods never read the register
directly: `methods.judgement` turns entries into method parameters and back into records.

Targets name what an entry applies to inside its scope: "" for the whole scope, an origin
label ("2021"), a development column by ages in months ("12-24") or a cell as origin and
column ("2021:12-24").
"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_WHO = "default"
ANY_SCOPE = "*"
CELL_SEPARATOR = ":"

Value = float | str | bool | None


class AssumptionError(ValueError):
    """A register entry is malformed or names something that does not exist."""


class Assumption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str  # specification ID, for example MT02
    name: str  # parameter of that specification, for example selected_factor
    scope: str = ANY_SCOPE  # group and measure, for example NON_LIFE/MOTOR_TPL/paid
    target: str = ""
    value: Value
    default: Value = None
    who: str = DEFAULT_WHO
    when: date | None = None
    why: str = ""

    @model_validator(mode="after")
    def _user_entries_say_why(self) -> "Assumption":
        if self.who != DEFAULT_WHO and not self.why.strip():
            raise ValueError(
                f"{self.method} {self.name} {self.target!r}: an entry by {self.who} needs a reason"
            )
        return self

    @property
    def is_default(self) -> bool:
        return self.who == DEFAULT_WHO


class AssumptionsRegister(BaseModel):
    """User entries. Within one method and name, an entry for the exact scope wins over one
    for every scope (ANY_SCOPE); two entries for the same scope and target are an error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[Assumption, ...] = ()

    @model_validator(mode="after")
    def _no_duplicates(self) -> "AssumptionsRegister":
        seen: set[tuple[str, str, str, str]] = set()
        for e in self.entries:
            key = (e.method, e.name, e.scope, e.target)
            if key in seen:
                raise ValueError(f"two register entries for {' '.join(key)}")
            seen.add(key)
        return self

    def find(self, method: str, name: str, scope: str) -> dict[str, Assumption]:
        """Entries of `method` and `name` in force for `scope`, by target."""
        found: dict[str, Assumption] = {}
        for wanted in (ANY_SCOPE, scope):  # the exact scope overwrites the general one
            for e in self.entries:
                if e.method == method and e.name == name and e.scope == wanted:
                    found[e.target] = e
        return found

    @classmethod
    def from_yaml(cls, path: Path) -> "AssumptionsRegister":
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return cls.model_validate({"entries": data.get("entries", [])})


def column_label(ages: Sequence[int], j: int) -> str:
    """Development column j, from age j to age j + 1, as "12-24"."""
    return f"{ages[j]}-{ages[j + 1]}"


def cell_label(origin: str, ages: Sequence[int], j: int) -> str:
    """The link ratio of `origin` in column j, as "2021:12-24"."""
    return f"{origin}{CELL_SEPARATOR}{column_label(ages, j)}"


def parse_cell(target: str, origins: Sequence[str], ages: Sequence[int]) -> tuple[int, int]:
    """(origin index, column index) of a cell target; AssumptionError when it does not exist."""
    origin, _, column = target.partition(CELL_SEPARATOR)
    columns = [column_label(ages, j) for j in range(len(ages) - 1)]
    if origin not in origins or column not in columns:
        raise AssumptionError(f"cell {target!r} is not a link ratio of this triangle")
    return origins.index(origin), columns.index(column)


def records(entries: Sequence[Assumption]) -> list[dict[str, Any]]:
    """The entries as plain rows for the manifest and the report."""
    return [e.model_dump(mode="json") for e in entries]
