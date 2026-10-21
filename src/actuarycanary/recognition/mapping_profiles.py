"""Mapping profiles (blueprint 6.3): a confirmed mapping saved as a small, editable YAML file.

A profile is keyed by the fingerprint of the sheet's header set (the exact header texts,
order ignored) and stored as ``<profiles folder>/<fingerprint>.yaml``. The next time a sheet
with the same headers appears, the profile is applied without asking. Anyone may edit a
profile: change a column's ``field``, leave it empty to ignore the column, or set
``concept`` to empty so that sheets with this layout are skipped.
"""

import hashlib
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROFILE_VERSION = 1
FINGERPRINT_LENGTH = 16
SUFFIX = ".yaml"

_HEADER_COMMENT = (
    "# Mapping profile: how sheets with these column headers are read.\n"
    "# Edit `field` to change a mapping or leave it empty to ignore the column; set `concept`\n"
    "# to empty to skip such sheets. Personal-data columns are dropped whatever is set here.\n"
)


class ProfileError(ValueError):
    """A profile file cannot be read or does not fit its layout."""


def fingerprint(headers: tuple[str, ...] | list[str]) -> str:
    """Fingerprint of a header set: the exact texts, sorted, so column order does not matter."""
    text = "\n".join(sorted(headers))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


class ProfileColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: str
    field: str | None = None
    layer: str = ""  # how the mapping was first made: dictionary, fuzzy, user, ...
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence: str = ""


class MappingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_version: int = PROFILE_VERSION
    fingerprint: str
    concept: str | None
    confirmed_on: date
    headers: list[str] = Field(min_length=1)
    columns: list[ProfileColumn]

    @model_validator(mode="after")
    def _fits_headers(self) -> "MappingProfile":
        if fingerprint(self.headers) != self.fingerprint:
            raise ValueError("fingerprint does not match the headers")
        unknown = [c.header for c in self.columns if c.header not in self.headers]
        if unknown:
            raise ValueError(f"columns not in headers: {unknown}")
        fields = [c.field for c in self.columns if c.field]
        if len(fields) != len(set(fields)):
            raise ValueError("a field is mapped from more than one column")
        return self

    def field_of(self, header: str) -> str | None:
        return next((c.field for c in self.columns if c.header == header), None)


def profile_path(folder: Path, key: str) -> Path:
    return folder / f"{key}{SUFFIX}"


def dump_profile(profile: MappingProfile) -> str:
    body = yaml.safe_dump(
        profile.model_dump(mode="json"), allow_unicode=True, sort_keys=False, width=100
    )
    return _HEADER_COMMENT + body


def save_profile(folder: Path, profile: MappingProfile) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = profile_path(folder, profile.fingerprint)
    path.write_text(dump_profile(profile), encoding="utf-8", newline="\n")
    return path


def read_profile(path: Path) -> tuple[MappingProfile, str]:
    """The profile in `path` and the SHA-256 of the file's bytes."""
    try:
        data = path.read_bytes()
        profile = MappingProfile.model_validate(yaml.safe_load(data.decode("utf-8")))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as error:
        raise ProfileError(f"{path}: {error}") from error
    return profile, hashlib.sha256(data).hexdigest()


def load_profile(folder: Path | None, key: str) -> tuple[MappingProfile, str] | None:
    """The saved profile for a fingerprint and its file's SHA-256, or None when there is none."""
    if folder is None:
        return None
    path = profile_path(folder, key)
    return read_profile(path) if path.is_file() else None


def profile_sha256(profile: MappingProfile) -> str:
    """SHA-256 of the profile's content as `save_profile` writes it."""
    return hashlib.sha256(dump_profile(profile).encode("utf-8")).hexdigest()
