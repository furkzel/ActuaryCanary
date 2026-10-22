"""Reads every specification file from spec/, validates it and checks cross-references."""

from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from actuarycanary.spec.catalogue import SpecCatalogue, SpecFile
from actuarycanary.spec.models import (
    ColumnAliasSpec,
    ConventionSpec,
    DataConceptSpec,
    FindingRulesSpec,
    MeasureSpec,
    MethodSpec,
    ModuleSpec,
    SpecBase,
    ValueAliasSpec,
)
from actuarycanary.spec.references import reference_problems

SPEC_FOLDER_NAME = "spec"

# Folder name -> model. Folders are read in this order, which is also the index order.
KIND_MODELS: dict[str, type[SpecBase]] = {
    "data": DataConceptSpec,
    "conventions": ConventionSpec,
    "measures": MeasureSpec,
    "methods": MethodSpec,
    "modules": ModuleSpec,
}
ALIAS_MODELS: dict[str, type[SpecBase]] = {
    "columns.yaml": ColumnAliasSpec,
    "values.yaml": ValueAliasSpec,
}
# Report specifications: one file per kind of rule, named by what it holds.
REPORT_MODELS: dict[str, type[SpecBase]] = {"findings.yaml": FindingRulesSpec}
NAMED_FILE_KINDS = ("aliases", "report")

_YamlLoader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class SpecError(Exception):
    """One or more specification files are invalid; `problems` lists each one."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(problems))


def find_spec_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the first folder holding spec/data/."""
    here = (start or Path(__file__)).resolve()
    for folder in (here, *here.parents):
        candidate = folder / SPEC_FOLDER_NAME
        if (candidate / "data").is_dir():
            return candidate
    raise FileNotFoundError(f"{SPEC_FOLDER_NAME}/data/ not found above {here}")


def _read_one(kind: str, model: type[SpecBase], path: Path) -> tuple[SpecFile | None, str | None]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_YamlLoader)
        spec = model.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as error:
        return None, f"{path.as_posix()}: {error}"
    named_after_id = path.stem == spec.id or path.stem.startswith(f"{spec.id}-")
    if kind not in NAMED_FILE_KINDS and not named_after_id:
        return None, f"{path.as_posix()}: file name must start with the spec id {spec.id}"
    return SpecFile(kind, path, spec), None


def read_spec_files(root: Path) -> tuple[list[SpecFile], list[str]]:
    """Parse and validate every file; return the valid ones and one problem per bad file."""
    jobs: list[tuple[str, type[SpecBase], Path]] = [
        (kind, model, path)
        for kind, model in KIND_MODELS.items()
        for path in sorted((root / kind).glob("*.yaml"))
    ]
    jobs += [("aliases", model, root / "aliases" / name) for name, model in ALIAS_MODELS.items()]
    jobs += [("report", model, root / "report" / name) for name, model in REPORT_MODELS.items()]
    files: list[SpecFile] = []
    problems: list[str] = []
    for kind, model, path in jobs:
        if not path.is_file():
            problems.append(f"{path.as_posix()}: missing")
            continue
        spec_file, problem = _read_one(kind, model, path)
        if spec_file:
            files.append(spec_file)
        if problem:
            problems.append(problem)
    return files, problems


def duplicate_id_problems(files: list[SpecFile]) -> list[str]:
    counts = Counter(f.spec.id for f in files)
    return [f"spec id {spec_id} is used {n} times" for spec_id, n in counts.items() if n > 1]


def load_specs(root: Path | None = None) -> SpecCatalogue:
    """Load all specs; raise SpecError listing every invalid file, repeated ID or bad reference."""
    files, problems = read_spec_files(root or find_spec_root())
    problems += duplicate_id_problems(files)
    if problems:
        raise SpecError(problems)
    catalogue = SpecCatalogue(tuple(files))
    problems = reference_problems(catalogue)
    if problems:
        raise SpecError(problems)
    return catalogue


def index_rows(catalogue: SpecCatalogue) -> list[tuple[str, str, str, str, str, str]]:
    """One row per spec: kind, id, version, status, English title, Turkish title."""
    return [
        (f.kind, f.spec.id, f.spec.version, f.spec.status.value, f.spec.title_en, f.spec.title_tr)
        for f in catalogue.files
    ]
