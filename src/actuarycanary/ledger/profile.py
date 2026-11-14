"""The account-mapping profile (CV12, record 0421): a small, editable YAML file, one per chart of
accounts, saved beside the column mapping profiles as ``ledger-<fingerprint>.yaml``.

The fingerprint is that of the sorted set of distinct account codes, so the same chart is
recognised in the next run and entities with the same chart share the file. A rule names an
entity (empty: every entity), an account pattern (an exact code or a prefix ending in ``*``), the
class, the sign, the balance kind and optionally a line. ``confirmed_on`` is empty until a person
sets it; a run with an unconfirmed profile uses it and says so.

Precedence between two rules that both match an account: the longer pattern (the characters
before the star) wins; of the same length an exact code beats a prefix; of the same again a rule
of an entity beats a general rule; two rules still equal are a profile error.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from actuarycanary.ledger.classes import AccountClass, BalanceKind
from actuarycanary.recognition.mapping_profiles import ProfileError

PROFILE_VERSION = 1
FINGERPRINT_LENGTH = 16
PREFIX = "ledger-"
SUFFIX = ".yaml"

_HEADER_COMMENT = (
    "# Account-mapping profile of a chart of accounts (CV12).\n"
    "# One rule per line: `entity` (empty: every entity), `pattern` (an account code, or a prefix\n"
    "# ending in *), `account_class`, `sign` (+1 or -1, to a positive platform amount),\n"
    "# `balance_kind` (PERIOD or YEAR_TO_DATE) and `line`. The longest pattern wins. Accounts no\n"
    "# rule matches stay unmapped. Set `confirmed_on` to a date once the mapping is checked.\n"
)


def chart_fingerprint(accounts: Iterable[str]) -> str:
    """Fingerprint of a chart of accounts: the distinct codes, sorted."""
    text = "\n".join(sorted(set(accounts)))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


class AccountRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str | None = None
    pattern: str
    account_class: AccountClass
    sign: Literal[1, -1]
    balance_kind: BalanceKind
    line: str | None = None

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, value: str) -> str:
        if not value or "*" in value[:-1]:
            raise ValueError("a pattern is an account code or a prefix with one * at the end")
        return value

    @property
    def literal(self) -> str:
        return self.pattern.removesuffix("*")

    @property
    def exact(self) -> bool:
        return not self.pattern.endswith("*")

    def matches(self, entity: str, account: str) -> bool:
        if self.entity not in (None, entity):
            return False
        return account == self.pattern if self.exact else account.startswith(self.literal)

    @property
    def precedence(self) -> tuple[int, bool, bool]:
        return (len(self.literal), self.exact, self.entity is not None)


class AccountProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_version: int = PROFILE_VERSION
    fingerprint: str
    confirmed_on: date | None = None
    accounts: list[str] = Field(min_length=1)  # the chart the fingerprint stands for
    rules: list[AccountRule]

    @model_validator(mode="after")
    def _fits_chart(self) -> "AccountProfile":
        if chart_fingerprint(self.accounts) != self.fingerprint:
            raise ValueError("fingerprint does not match the accounts")
        return self

    @property
    def confirmed(self) -> bool:
        return self.confirmed_on is not None


@dataclass(frozen=True)
class Tie:
    """Two rules of the same precedence that both match an account: a profile error."""

    entity: str
    account: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class Assignment:
    """What the profile says about each (entity, account) pair of a ledger."""

    rules: dict[tuple[str, str], AccountRule]
    unmapped: tuple[tuple[str, str], ...]
    ties: tuple[Tie, ...]


def assign(profile: AccountProfile, pairs: Iterable[tuple[str, str]]) -> Assignment:
    """The winning rule of every (entity, account) pair, the pairs no rule matches, and the pairs
    two rules of the same precedence claim (those have no rule: their accounts are not
    reconciled)."""
    rules: dict[tuple[str, str], AccountRule] = {}
    unmapped: list[tuple[str, str]] = []
    ties: list[Tie] = []
    for entity, account in sorted(set(pairs)):
        hits = [r for r in profile.rules if r.matches(entity, account)]
        if not hits:
            unmapped.append((entity, account))
            continue
        best = max(r.precedence for r in hits)
        winners = [r for r in hits if r.precedence == best]
        if len(winners) > 1:
            ties.append(Tie(entity, account, tuple(sorted(r.pattern for r in winners))))
        else:
            rules[(entity, account)] = winners[0]
    return Assignment(rules, tuple(unmapped), tuple(ties))


def profile_path(folder: Path, fingerprint: str) -> Path:
    return folder / f"{PREFIX}{fingerprint}{SUFFIX}"


def dump_profile(profile: AccountProfile) -> str:
    data = profile.model_dump(mode="json")
    data["confirmed_on"] = profile.confirmed_on  # a date, written as one
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    return _HEADER_COMMENT + body


def profile_sha256(profile: AccountProfile) -> str:
    """SHA-256 of the profile's content as `save_profile` writes it."""
    return hashlib.sha256(dump_profile(profile).encode("utf-8")).hexdigest()


def save_profile(folder: Path, profile: AccountProfile) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = profile_path(folder, profile.fingerprint)
    path.write_text(dump_profile(profile), encoding="utf-8", newline="\n")
    return path


def read_profile(path: Path) -> tuple[AccountProfile, str]:
    """The profile in `path` and the SHA-256 of the file's bytes."""
    try:
        data = path.read_bytes()
        profile = AccountProfile.model_validate(yaml.safe_load(data.decode("utf-8")))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as error:
        raise ProfileError(f"{path}: {error}") from error
    return profile, hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ProfileInUse:
    """The profile a run uses, where it is saved (None when the run has no profiles folder) and
    whether it was read from there (`saved`) or proposed in this run."""

    profile: AccountProfile
    sha256: str
    path: Path | None
    saved: bool

    @property
    def status(self) -> str:
        return "confirmed" if self.profile.confirmed else "proposed"
