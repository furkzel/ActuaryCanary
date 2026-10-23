"""Cross-reference checks: every reference in a spec points at something that is defined."""

from collections import Counter, defaultdict
from collections.abc import Iterable

from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.spec.labels import normalise_label
from actuarycanary.spec.models import ConventionSpec, MeasureSpec, MethodSpec


def reference_problems(catalogue: SpecCatalogue) -> list[str]:
    """Return one message per broken reference; an empty list means all references resolve."""
    return [
        *_data_problems(catalogue),
        *_usage_problems(catalogue),
        *_module_problems(catalogue),
        *_column_alias_problems(catalogue),
        *_value_alias_problems(catalogue),
        *_finding_rule_problems(catalogue),
        *_champion_problems(catalogue),
    ]


def field_exists(catalogue: SpecCatalogue, reference: str) -> bool:
    concept_id, _, field_name = reference.partition(".")
    concept = catalogue.data.get(concept_id)
    return concept is not None and concept.field(field_name) is not None


def _missing_fields(catalogue: SpecCatalogue, owner: str, refs: Iterable[str]) -> list[str]:
    return [
        f"{owner}: field {ref} is not defined in spec/data"
        for ref in refs
        if not field_exists(catalogue, ref)
    ]


def _data_problems(catalogue: SpecCatalogue) -> list[str]:
    problems: list[str] = []
    rule_ids: Counter[str] = Counter()
    for concept in catalogue.data.values():
        names = Counter(f.name for f in concept.fields)
        problems += [f"{concept.id}: field {n} is defined twice" for n, c in names.items() if c > 1]
        problems += [
            f"{concept.id}: key {k} is not a field" for k in concept.keys if k not in names
        ]
        references = [f.references for f in concept.fields if f.references]
        problems += _missing_fields(catalogue, concept.id, references)
        for rule in concept.validation:
            rule_ids[rule.id] += 1
            problems += _missing_fields(catalogue, f"{concept.id} {rule.id}", rule.fields)
    problems += [f"validation rule {r} is used {c} times" for r, c in rule_ids.items() if c > 1]
    return problems


def _usage_problems(catalogue: SpecCatalogue) -> list[str]:
    problems: list[str] = []
    specs: list[ConventionSpec | MeasureSpec | MethodSpec] = [
        *catalogue.conventions.values(),
        *catalogue.measures.values(),
        *catalogue.methods.values(),
    ]
    for spec in specs:
        problems += _missing_fields(catalogue, spec.id, [*spec.requires, *spec.optional])
        problems += [
            f"{spec.id}: uses {ref}, which is not a defined spec id"
            for ref in spec.uses
            if ref not in catalogue.ids or ref == spec.id
        ]
    return problems


def _module_problems(catalogue: SpecCatalogue) -> list[str]:
    problems: list[str] = []
    rule_ids = {rule.id for concept in catalogue.data.values() for rule in concept.validation}
    for module in catalogue.modules.values():
        problems += [
            f"{module.id}: blocking rule {r} is not defined in spec/data"
            for r in module.blocking_rules
            if r not in rule_ids
        ]
        if not module.required_all and not module.required_any:
            problems.append(f"{module.id}: needs required_all or required_any")
        concepts = [*module.required_all, *module.required_any, *module.optional]
        problems += [
            f"{module.id}: concept {c} is not defined in spec/data"
            for c in concepts
            if c not in catalogue.data
        ]
        problems += [
            f"{module.id}: measure {m} is not defined in spec/measures"
            for m in module.measures
            if m not in catalogue.measures
        ]
        problems += [
            f"{module.id}: method {m} is not defined in spec/methods"
            for m in module.methods
            if m not in catalogue.methods
        ]
        runs = [*module.measures, *module.methods]
        problems += [
            f"{module.id}: needs method {m} (used by its measures or methods) but does not list it"
            for m in sorted(_used_methods(catalogue, runs) - set(module.methods))
        ]
        problems += [
            f"{module.id}: its measures or methods require concept {c}, which it does not list"
            for c in sorted(_required_concepts(catalogue, runs) - set(concepts))
        ]
    return problems


def _uses(catalogue: SpecCatalogue, spec_id: str) -> list[str]:
    spec = catalogue.measures.get(spec_id) or catalogue.methods.get(spec_id)
    spec = spec or catalogue.conventions.get(spec_id)
    return spec.uses if spec else []


def _used_methods(catalogue: SpecCatalogue, spec_ids: list[str]) -> set[str]:
    """Every method reachable from `spec_ids` through `uses`, the start ids included."""
    seen: set[str] = set()
    pending = list(spec_ids)
    while pending:
        spec_id = pending.pop()
        if spec_id not in seen:
            seen.add(spec_id)
            pending += _uses(catalogue, spec_id)
    return seen & set(catalogue.methods)


def _required_concepts(catalogue: SpecCatalogue, spec_ids: list[str]) -> set[str]:
    specs = [catalogue.measures.get(i) or catalogue.methods.get(i) for i in spec_ids]
    return {ref.partition(".")[0] for spec in specs if spec for ref in spec.requires}


def _conflicts(owner: str, targets_by_token: dict[str, set[str]]) -> list[str]:
    return [
        f"{owner}: alias token '{token}' maps to {sorted(targets)}"
        for token, targets in targets_by_token.items()
        if len(targets) > 1
    ]


def _column_alias_problems(catalogue: SpecCatalogue) -> list[str]:
    """AL01, and AL03 when planned specs are loaded, are checked as one dictionary."""
    specs = catalogue.column_alias_specs
    owner = "+".join(spec.id for spec in specs)
    problems: list[str] = []
    covered: Counter[str] = Counter()
    tokens_by_concept: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for aliases in specs:
        for entry in aliases.columns:
            for concept in entry.concepts:
                ref = f"{concept}.{entry.field}"
                if not field_exists(catalogue, ref):
                    problems.append(f"{aliases.id}: {ref} is not defined in spec/data")
                covered[ref] += 1
                for label in [entry.field, *entry.aliases]:
                    tokens_by_concept[concept][normalise_label(label)].add(entry.field)
    for concept in catalogue.data.values():
        for field in concept.fields:
            ref = f"{concept.id}.{field.name}"
            if covered[ref] != 1:
                problems.append(f"{owner}: {ref} has {covered[ref]} alias entries, needs 1")
    for concept, tokens in tokens_by_concept.items():
        problems += _conflicts(f"{owner} {concept}", tokens)
    personal = {
        normalise_label(a)
        for aliases in specs
        for entry in aliases.personal_data
        for a in entry.aliases
    }
    for concept, tokens in tokens_by_concept.items():
        problems += [
            f"{owner}: '{token}' is both a {concept} field alias and personal data"
            for token in tokens
            if token in personal
        ]
    return problems


def _value_alias_problems(catalogue: SpecCatalogue) -> list[str]:
    """AL02, and AL04 when planned specs are loaded, are checked as one dictionary."""
    specs = catalogue.value_alias_specs
    owner = "+".join(spec.id for spec in specs)
    problems: list[str] = []
    covered: Counter[str] = Counter()
    for aliases, entry in ((a, e) for a in specs for e in a.values):
        tokens: dict[str, set[str]] = defaultdict(set)
        for label_class, labels in entry.classes.items():
            for label in [label_class, *labels]:
                tokens[normalise_label(label)].add(label_class)
        problems += _conflicts(f"{aliases.id} {entry.field}", tokens)
        for concept_id in entry.concepts:
            ref = f"{concept_id}.{entry.field}"
            concept = catalogue.data.get(concept_id)
            field = concept.field(entry.field) if concept else None
            if field is None:
                problems.append(f"{aliases.id}: {ref} is not defined in spec/data")
                continue
            covered[ref] += 1
            if set(field.classes) != set(entry.classes):
                problems.append(f"{aliases.id}: classes of {ref} differ from spec/data")
    for concept in catalogue.data.values():
        for field in concept.fields:
            ref = f"{concept.id}.{field.name}"
            if field.classes and covered[ref] != 1:
                problems.append(f"{owner}: {ref} has {covered[ref]} value entries, needs 1")
    return problems


def _champion_problems(catalogue: SpecCatalogue) -> list[str]:
    problems: list[str] = []
    for method in catalogue.methods.values():
        champion = method.champion
        if method.tier == "C" and champion is None:
            problems.append(f"{method.id}: a tier C method names its champion")
        elif champion is not None and (champion not in catalogue.methods or champion == method.id):
            problems.append(f"{method.id}: champion {champion} is not another defined method")
        elif champion is not None and catalogue.methods[champion].tier == "C":
            problems.append(f"{method.id}: champion {champion} is a tier C method")
    return problems


def _finding_rule_problems(catalogue: SpecCatalogue) -> list[str]:
    spec = catalogue.finding_rules
    counts = Counter(rule.id for rule in spec.rules)
    problems = [f"{spec.id}: rule {r} is defined {n} times" for r, n in counts.items() if n > 1]
    problems += [
        f"{spec.id} {rule.id}: evidence spec {ref} is not a defined spec id"
        for rule in spec.rules
        for ref in rule.evidence.specs
        if ref not in catalogue.ids
    ]
    return problems
