"""The loaded set of specifications, with typed access by kind."""

from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class SpecFile:
    kind: str
    path: Path
    spec: SpecBase


@dataclass(frozen=True)
class SpecCatalogue:
    files: tuple[SpecFile, ...]

    def _of_type[T: SpecBase](self, model: type[T]) -> dict[str, T]:
        return {f.spec.id: f.spec for f in self.files if isinstance(f.spec, model)}

    @property
    def data(self) -> dict[str, DataConceptSpec]:
        return self._of_type(DataConceptSpec)

    @property
    def conventions(self) -> dict[str, ConventionSpec]:
        return self._of_type(ConventionSpec)

    @property
    def measures(self) -> dict[str, MeasureSpec]:
        return self._of_type(MeasureSpec)

    @property
    def methods(self) -> dict[str, MethodSpec]:
        return self._of_type(MethodSpec)

    @property
    def modules(self) -> dict[str, ModuleSpec]:
        return self._of_type(ModuleSpec)

    @property
    def column_aliases(self) -> ColumnAliasSpec:
        return next(iter(self._of_type(ColumnAliasSpec).values()))

    @property
    def value_aliases(self) -> ValueAliasSpec:
        return next(iter(self._of_type(ValueAliasSpec).values()))

    @property
    def finding_rules(self) -> FindingRulesSpec:
        return next(iter(self._of_type(FindingRulesSpec).values()))

    @property
    def column_alias_specs(self) -> list[ColumnAliasSpec]:
        """AL01 and, in a catalogue with planned specs, the column aliases of planned concepts."""
        return list(self._of_type(ColumnAliasSpec).values())

    @property
    def value_alias_specs(self) -> list[ValueAliasSpec]:
        return list(self._of_type(ValueAliasSpec).values())

    @property
    def ids(self) -> set[str]:
        return {f.spec.id for f in self.files}

    def built(self) -> "SpecCatalogue":
        """The specs a run uses: every spec except those planned for a later version."""
        return SpecCatalogue(tuple(f for f in self.files if f.spec.implemented))
