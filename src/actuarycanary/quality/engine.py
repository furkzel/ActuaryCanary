"""Runs the checks, scores them (DQ01) and works out what each finding means for the modules."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

import polars as pl

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.quality.checks import CANONICAL_RULES, CAST_RULE, CHECKS, Context, from_canonical
from actuarycanary.quality.model import (
    DIMENSIONS,
    ConceptCoverage,
    ModuleStatus,
    Outcome,
    QualityFinding,
    QualityReport,
    RuleScore,
    Score,
)
from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.spec.models import ModuleSpec

WEIGHTS = {"BLOCKING": 3, "WARNING": 1, "INFO": 0}  # DQ01
# The date field that shows which period a concept covers.
PERIOD_FIELDS = {
    "claim_valuations": "valuation_date",
    "claims": "report_date",
    "policies": "start_date",
    "premiums": "booking_date",
    "expenses": "period",
    "market": "date",
}
DATA_MODULE = "M01"  # the quality report itself; never blocked by data faults


def dq01(rules: Iterable[RuleScore]) -> Score:
    """DQ01: weighted pass rate of the rules, 0 to 100; rules that checked nothing add nothing."""
    used = [r for r in rules if r.checked > 0]
    weight = sum(r.weight for r in used)
    if weight == 0:
        return Score(None, len(used))
    value = 100 * sum(r.weight * r.passed / r.checked for r in used) / weight
    return Score(value, len(used))


def _scores(groups: Mapping[str, Sequence[RuleScore]]) -> dict[str, Score]:
    return {key: dq01(rules) for key, rules in sorted(groups.items())}


def _rule_scores(
    outcomes: Sequence[Outcome], catalogue: SpecCatalogue
) -> tuple[list[RuleScore], dict[tuple[str, str], str]]:
    """One score per (concept, rule); several messages of a rule add up, capped at the rows."""
    meta: dict[tuple[str, str], tuple[str, str, tuple[str, ...], str]] = {}
    for concept, spec in catalogue.data.items():
        for rule in spec.validation:
            meta[(concept, rule.id)] = (
                rule.dimension,
                rule.severity,
                tuple(rule.fields),
                rule.rule,
            )
        meta[(concept, CAST_RULE)] = (
            "validity",
            "WARNING",
            (),
            "Every value is of the type of its field.",
        )
    checked: dict[tuple[str, str], int] = {}
    failed: dict[tuple[str, str], int] = defaultdict(int)
    for o in outcomes:
        key = (o.concept, o.rule)
        checked[key] = max(checked.get(key, 0), o.checked)
        failed[key] += o.failed
    scores = []
    for key, rows in checked.items():
        dimension, severity, fields, _ = meta[key]
        scores.append(
            RuleScore(
                key[1], key[0], dimension, severity, WEIGHTS[severity], fields, rows,
                min(failed[key], rows),
            )
        )  # fmt: skip
    return scores, {key: value[3] for key, value in meta.items()}


def _items(module: ModuleSpec, catalogue: SpecCatalogue) -> dict[str, tuple[set[str], set[str]]]:
    """The fields each measure and method of the module requires and may use."""
    items: dict[str, tuple[set[str], set[str]]] = {}
    for item in module.measures:
        spec = catalogue.measures[item]
        items[item] = (set(spec.requires), set(spec.optional))
    for item in module.methods:
        spec = catalogue.methods[item]
        items[item] = (set(spec.requires), set(spec.optional))
    return items


def _module_status(
    module: ModuleSpec,
    catalogue: SpecCatalogue,
    loaded: set[str],
    blocking: Sequence[QualityFinding],
) -> ModuleStatus:
    """A module cannot run when a required concept is missing or a BLOCKING finding hits a
    field that its measures or methods require from a required concept; any other BLOCKING
    finding only removes the measures and methods that use that field or, failing that, any field
    of the concept (a key that cannot be trusted spoils every use of the concept)."""
    if module.id == DATA_MODULE:
        return ModuleStatus(module.id, module.title_en, "ok")
    title = module.title_en
    missing = [c for c in module.required_all if c not in loaded]
    if missing or (module.required_any and not loaded.intersection(module.required_any)):
        return ModuleStatus(module.id, title, "unable", (module.skip_reason,))
    items = _items(module, catalogue)
    required = set().union(*(req for req, _ in items.values())) if items else set()
    unable: list[str] = []
    unavailable: set[str] = set()
    limited: list[str] = []
    for f in blocking:
        reason = f"{f.rule}: {f.message} ({f.count} of {f.checked})"
        if f.concept in module.required_all and set(f.fields) & required:
            unable.append(reason)
            continue
        prefix = f"{f.concept}."
        hit = [
            i
            for i, (req, opt) in items.items()
            if set(f.fields) & (req | opt) or any(x.startswith(prefix) for x in req | opt)
        ]
        if hit:
            limited.append(reason)
            unavailable.update(hit)
    if unable:
        return ModuleStatus(module.id, title, "unable", tuple(unable))
    if limited:
        return ModuleStatus(module.id, title, "limited", tuple(limited), tuple(sorted(unavailable)))
    return ModuleStatus(module.id, title, "ok")


def _affected(fields: Sequence[str], catalogue: SpecCatalogue) -> tuple[str, ...]:
    """Modules whose measures or methods use any of `fields`, required or optional."""
    wanted = set(fields)
    result = []
    for module in catalogue.modules.values():
        if module.id == DATA_MODULE:
            continue
        used: set[str] = set()
        for item in (*module.measures, *module.methods):
            spec = catalogue.measures.get(item) or catalogue.methods[item]
            used |= set(spec.requires) | set(spec.optional)
        if wanted & used:
            result.append(module.id)
    return tuple(sorted(result))


def _range(frame: pl.DataFrame, field: str) -> tuple[date | None, date | None]:
    """Earliest and latest date of `field`, or None when it is absent or empty."""
    if field not in frame.columns:
        return None, None
    low, high = frame.select(
        pl.col(field).min().alias("low"), pl.col(field).max().alias("high")
    ).row(0)
    return (low if isinstance(low, date) else None, high if isinstance(high, date) else None)


def _coverage(
    catalogue: SpecCatalogue,
    frames: Mapping[str, pl.DataFrame],
    raw: Mapping[str, pl.DataFrame],
    sources: Mapping[str, Sequence[str]],
    unreadable: Mapping[str, str],
) -> tuple[ConceptCoverage, ...]:
    result = []
    for concept in catalogue.data:
        frame = frames.get(concept)
        if frame is None:
            note = unreadable.get(concept, "not found in the input")
            result.append(
                ConceptCoverage(concept, False, sources=tuple(sources.get(concept, ())), note=note)
            )
            continue
        first, last = _range(frame, PERIOD_FIELDS[concept])
        result.append(
            ConceptCoverage(
                concept, True, raw[concept].height, tuple(sources.get(concept, ())), first, last
            )
        )
    return tuple(result)


def evaluate(
    catalogue: SpecCatalogue,
    feeds: Mapping[str, CanonicalFeed],
    raw: Mapping[str, pl.DataFrame],
    sources: Mapping[str, Sequence[str]] | None = None,
    cut_off: date | None = None,
    unreadable: Mapping[str, str] | None = None,
    reporting_currency: str | None = None,
    price_index: str | None = None,
    adjusted: bool = False,
) -> QualityReport:
    """The quality report of the loaded feeds. `raw` holds each concept's table as read, before
    the canonical rules, so that rows read and source references are complete. The reporting
    currency, price index and value basis tell DV-MKT-07 which series the run needs."""
    frames = {c: feed.frame for c, feed in feeds.items()}
    if cut_off is None and "claim_valuations" in frames:
        cut_off = _range(frames["claim_valuations"], "valuation_date")[1]
    ctx = Context(frames, catalogue.data, cut_off, reporting_currency, price_index, adjusted)
    outcomes: list[Outcome] = []
    not_evaluated: list[tuple[str, str]] = []
    for concept, feed in feeds.items():
        outcomes += from_canonical(concept, feed.findings, raw[concept])
        for rule in catalogue.data[concept].validation:
            if rule.id in CANONICAL_RULES.get(concept, ()):
                continue
            check = CHECKS.get(rule.id)
            if check is None:
                not_evaluated.append((rule.id, "no check is implemented for this rule yet"))
            elif (outcome := check(ctx)) is None:
                not_evaluated.append((rule.id, "the fields it needs are not loaded"))
            else:
                outcomes.append(outcome)
    for concept, spec in catalogue.data.items():
        if concept not in feeds:
            why = (unreadable or {}).get(concept, f"{concept} is not loaded")
            not_evaluated += [(r.id, why) for r in spec.validation]

    scores, text = _rule_scores(outcomes, catalogue)
    not_evaluated += [(s.rule, "it checked no rows") for s in scores if s.checked == 0]
    used = [s for s in scores if s.checked > 0]
    by_concept: dict[str, list[RuleScore]] = defaultdict(list)
    by_field: dict[str, list[RuleScore]] = defaultdict(list)
    by_dimension: dict[str, list[RuleScore]] = defaultdict(list)
    for s in used:
        by_concept[s.concept].append(s)
        by_dimension[s.dimension].append(s)
        for field in s.fields:
            by_field[field].append(s)
    meta = {(s.concept, s.rule): s for s in scores}

    findings: list[QualityFinding] = []
    for o in outcomes:
        if o.failed == 0:
            continue
        s = meta[(o.concept, o.rule)]
        fields = s.fields or tuple(
            f"{o.concept}.{f}" for f in _cast_fields(o.message, feeds[o.concept])
        )
        findings.append(
            QualityFinding(
                o.rule, o.concept, s.dimension, s.severity, o.failed, s.checked,
                o.message or f"Rule not met: {text[(o.concept, o.rule)]}", fields, o.refs,
                _affected(fields, catalogue),
            )
        )  # fmt: skip
    order = {"BLOCKING": 0, "WARNING": 1, "INFO": 2}
    findings.sort(key=lambda f: (order[f.severity], f.concept, f.rule, f.message))
    blocking = [f for f in findings if f.severity == "BLOCKING"]
    modules = tuple(
        _module_status(m, catalogue, set(feeds), blocking) for m in catalogue.modules.values()
    )
    return QualityReport(
        cut_off,
        dq01(used),
        _scores(by_concept),
        _scores(by_field),
        {d: dq01(by_dimension[d]) for d in DIMENSIONS if d in by_dimension},
        tuple(sorted(used, key=lambda s: (s.concept, s.rule))),
        tuple(findings),
        modules,
        _coverage(catalogue, frames, raw, sources or {}, unreadable or {}),
        tuple(sorted(not_evaluated)),
    )


def _cast_fields(message: str, feed: CanonicalFeed) -> list[str]:
    """The field named at the start of a cast finding message (`field: values that ...`)."""
    name = message.split(":", 1)[0]
    return [name] if name in feed.fields else []
