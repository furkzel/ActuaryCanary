"""Project metadata loaded from project.yaml through a validated model."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

PROJECT_FILE_NAME = "project.yaml"


class ReportSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    languages: list[str]
    default_reporting_currency: str
    default_price_index: str
    disclaimer: str


class DataSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    synthetic_mode: str


class ProjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    package: str
    command: str
    tagline: str
    version: str
    author: str
    contact: str
    repository: str
    licence: str
    report: ReportSettings
    data: DataSettings
    # the large-loss section (CV08 1.1.0, record 0601); read by `parse_large_loss`
    large_loss: dict[str, Any] | None = None


def find_project_file(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the first project.yaml."""
    here = (start or Path(__file__)).resolve()
    for folder in (here, *here.parents):
        candidate = folder / PROJECT_FILE_NAME
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{PROJECT_FILE_NAME} not found above {here}")


def load_metadata(path: Path | None = None) -> ProjectMetadata:
    source = path or find_project_file()
    return ProjectMetadata.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
