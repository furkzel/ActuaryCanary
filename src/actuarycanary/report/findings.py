"""Key findings from the fixed rules of RP01 (`spec/report/findings.yaml`, decision 0070).

A rule fires when every clause of its condition holds on the facts of its scope; its sentence
is the template with each `{fact}` formatted by the fact's kind. Nothing else writes text: a
fact that is not known keeps the rule from firing, and a template naming an unknown fact is
an error in the specification.
"""

import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from actuarycanary.report import language, numbers
from actuarycanary.spec.models import FindingRule

Kind = Literal["amount", "ratio", "factor", "count", "score", "text"]
OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    ">": operator.gt,
}
_CLAUSE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*(<=|>=|==|!=|<|>)\s*(\S+)\s*$")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
KEY_FINDINGS = 8  # sentences shown under key findings; the rest follow as further findings


class RuleError(ValueError):
    """A rule's condition or template cannot be read."""


@dataclass(frozen=True)
class Fact:
    value: float | str
    kind: Kind

    def show(self) -> str:
        value = self.value
        if self.kind == "text" or isinstance(value, str):
            return str(value)
        formatter = {
            "amount": numbers.amount,
            "ratio": numbers.ratio,
            "factor": numbers.factor,
            "count": numbers.count,
            "score": numbers.score,
        }[self.kind]
        return formatter(value)


Facts = Mapping[str, Fact]


@dataclass(frozen=True)
class Clause:
    fact: str
    op: str
    other: str  # a number or a fact name


def parse_condition(condition: str) -> tuple[Clause, ...]:
    clauses = []
    for part in condition.split(" and "):
        found = _CLAUSE.match(part)
        if found is None:
            raise RuleError(f"cannot read the clause '{part.strip()}' of '{condition}'")
        clauses.append(Clause(found[1], found[2], found[3]))
    return tuple(clauses)


def facts_named(rule: FindingRule) -> set[str]:
    """Every fact a rule reads: in its condition and in its template."""
    named = {c.fact for c in parse_condition(rule.condition)}
    named |= {c.other for c in parse_condition(rule.condition) if not _NUMBER.match(c.other)}
    return (
        named
        | set(_PLACEHOLDER.findall(rule.template))
        | set(_PLACEHOLDER.findall(rule.template_tr))
    )


def _number(facts: Facts, name: str) -> float | None:
    if _NUMBER.match(name):
        return float(name)
    fact = facts.get(name)
    if fact is None or isinstance(fact.value, str):
        return None
    return float(fact.value)


def holds(rule: FindingRule, facts: Facts) -> bool:
    """The condition on these facts; False when a fact it reads is not known."""
    for clause in parse_condition(rule.condition):
        left, right = _number(facts, clause.fact), _number(facts, clause.other)
        if left is None or right is None or not OPERATORS[clause.op](left, right):
            return False
    return True


def sentence(rule: FindingRule, facts: Facts) -> str:
    """The rule's sentence in the language of the report, each fact formatted by its kind."""
    template = rule.template_tr if language.current() == language.TURKISH else rule.template

    def fill(found: re.Match[str]) -> str:
        name = found[1]
        if name not in facts:
            raise RuleError(f"{rule.id}: the template names {name}, which is not a fact here")
        return facts[name].show()

    return " ".join(_PLACEHOLDER.sub(fill, template).split())


@dataclass(frozen=True)
class KeyFinding:
    rule: str
    title: str
    scope: str
    key: str  # "" for the run, the segment, or "segment · line"
    priority: int
    text: str
    section: str  # anchor of the evidence in the report
    files: tuple[str, ...]
    specs: tuple[str, ...]
    banner: bool

    def record(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "title": self.title,
            "scope": self.scope,
            "key": self.key,
            "text": self.text,
            "section": self.section,
            "files": list(self.files),
            "specs": list(self.specs),
            "banner": self.banner,
        }


def evaluate(
    rules: list[FindingRule],
    scoped: Mapping[str, list[tuple[str, str, Facts]]],
) -> list[KeyFinding]:
    """Fire every rule on each fact set of its scope. `scoped` maps a scope to its fact sets as
    (key shown, anchor of the key, facts); the anchor replaces the section `line`."""
    fired: list[KeyFinding] = []
    for rule in rules:
        for key, anchor, facts in scoped.get(rule.scope, []):
            if not holds(rule, facts):
                continue
            section = rule.evidence.section
            fired.append(
                KeyFinding(
                    rule.id,
                    rule.title_tr if language.current() == language.TURKISH else rule.title,
                    rule.scope,
                    key,
                    rule.priority,
                    sentence(rule, facts),
                    anchor if section == "line" else section,
                    tuple(rule.evidence.files),
                    tuple(rule.evidence.specs),
                    rule.banner,
                )
            )
    return sorted(fired, key=lambda f: (f.priority, f.rule, f.key))


__all__ = [
    "KEY_FINDINGS",
    "Fact",
    "Facts",
    "KeyFinding",
    "RuleError",
    "evaluate",
    "facts_named",
    "holds",
    "parse_condition",
    "sentence",
]
