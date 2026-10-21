"""The alias dictionaries (AL01 columns, AL02 values) as lookups by normalised token.

Every label is compared after ``normalise_label`` (blueprint 6.3 layer 1), so ``ÖDEME TARİHİ``,
``Odeme_Tarihi`` and ``ODEMETARIHI`` are one token. Within a concept a token points at one
field only, and no token is both a field alias and personal data; the spec loader checks both.
"""

from dataclasses import dataclass, field

from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.spec.labels import normalise_label
from actuarycanary.spec.models import DataConceptSpec


@dataclass(frozen=True)
class Alias:
    field: str
    label: str  # as written in the dictionary, for evidence
    token: str


@dataclass(frozen=True)
class Dictionary:
    concepts: dict[str, DataConceptSpec]
    columns: dict[str, dict[str, Alias]]  # concept -> token -> alias
    personal: dict[str, tuple[str, str]]  # token -> (kind, label)
    values: dict[tuple[str, str], dict[str, str]]  # (concept, field) -> token -> class
    spec_versions: dict[str, str] = field(default_factory=dict)  # AL01, AL02 -> version

    @property
    def field_tokens(self) -> frozenset[str]:
        """Tokens that name a field of any concept."""
        return frozenset(token for lookup in self.columns.values() for token in lookup)


def build_dictionary(specs: SpecCatalogue) -> Dictionary:
    concepts = specs.data
    columns: dict[str, dict[str, Alias]] = {c: {} for c in concepts}
    for entry in specs.column_aliases.columns:
        for concept in entry.concepts:
            for label in (entry.field, *entry.aliases):
                token = normalise_label(label)
                columns[concept].setdefault(token, Alias(entry.field, label, token))
    personal = {
        normalise_label(label): (entry.kind, label)
        for entry in specs.column_aliases.personal_data
        for label in entry.aliases
    }
    values: dict[tuple[str, str], dict[str, str]] = {}
    for entry in specs.value_aliases.values:
        lookup: dict[str, str] = {}
        for label_class, labels in entry.classes.items():
            for label in (label_class, *labels):
                lookup[normalise_label(label)] = label_class
        for concept in entry.concepts:
            values[(concept, entry.field)] = lookup
    versions = {
        specs.column_aliases.id: specs.column_aliases.version,
        specs.value_aliases.id: specs.value_aliases.version,
    }
    return Dictionary(concepts, columns, personal, values, versions)
