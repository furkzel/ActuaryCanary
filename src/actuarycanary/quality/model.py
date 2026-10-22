"""Data shapes of the quality report: outcomes of checks, findings, scores, module status."""

from dataclasses import dataclass, field
from datetime import date

SEVERITIES = ("BLOCKING", "WARNING", "INFO")
DIMENSIONS = ("completeness", "validity", "consistency", "uniqueness", "reasonableness", "coverage")
EXAMPLES = 5  # source references kept per finding; the count is always complete


@dataclass(frozen=True)
class SourceRef:
    file: str
    sheet: str
    row: int


@dataclass(frozen=True)
class Outcome:
    """One rule evaluated on one concept: rows (or pairs, claims) checked and failing."""

    rule: str
    concept: str
    checked: int
    failed: int
    message: str = ""
    refs: tuple[SourceRef, ...] = ()


@dataclass(frozen=True)
class RuleScore:
    """The pass rate of one rule, the input of DQ01."""

    rule: str
    concept: str
    dimension: str
    severity: str
    weight: int
    fields: tuple[str, ...]
    checked: int
    failed: int

    @property
    def passed(self) -> int:
        return self.checked - self.failed


@dataclass(frozen=True)
class QualityFinding:
    rule: str
    concept: str
    dimension: str
    severity: str
    count: int
    checked: int
    message: str
    fields: tuple[str, ...]
    refs: tuple[SourceRef, ...]
    modules: tuple[str, ...]  # modules whose result this finding can change


@dataclass(frozen=True)
class ModuleStatus:
    module: str
    title: str
    status: str  # "ok", "limited" or "unable"
    reasons: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()  # measures and methods that cannot be produced


@dataclass(frozen=True)
class ConceptCoverage:
    concept: str
    loaded: bool
    rows: int = 0
    sources: tuple[str, ...] = ()  # "file [sheet]"
    first: date | None = None
    last: date | None = None
    note: str = ""


@dataclass(frozen=True)
class Score:
    value: float | None  # 0 to 100; None when no rule was evaluated
    rules: int


@dataclass(frozen=True)
class QualityReport:
    cut_off: date | None
    overall: Score
    by_concept: dict[str, Score]
    by_field: dict[str, Score]
    by_dimension: dict[str, Score]
    rules: tuple[RuleScore, ...]
    findings: tuple[QualityFinding, ...]
    modules: tuple[ModuleStatus, ...]
    coverage: tuple[ConceptCoverage, ...]
    not_evaluated: tuple[tuple[str, str], ...] = field(default=())  # (rule, reason)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)
