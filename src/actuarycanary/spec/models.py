"""Validated models for every kind of specification file in spec/.

Field references are written as ``concept.field`` (for example ``claims.report_date``).
Spec references are written as a spec ID (for example ``PR02`` or ``MT03``).
"""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
SNAKE_PATTERN = r"^[a-z][a-z0-9_]*$"
CLASS_PATTERN = r"^[A-Z][A-Z0-9_]*$"
FIELD_REF_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"

ParameterValue = str | int | float | bool | list[str] | list[float] | None


class Status(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChangeLogEntry(_Strict):
    version: str = Field(pattern=SEMVER_PATTERN)
    date: date
    change: str


class SpecBase(_Strict):
    id: str
    version: str = Field(pattern=SEMVER_PATTERN)
    title_en: str = Field(min_length=1)
    title_tr: str = Field(min_length=1)
    status: Status
    definition: str = Field(min_length=1)
    notes: str = ""
    change_log: list[ChangeLogEntry] = Field(min_length=1)


class Parameter(_Strict):
    name: str = Field(pattern=SNAKE_PATTERN)
    default: ParameterValue
    description: str
    allowed: list[str] | None = None


class Formula(_Strict):
    name: str
    expression: str
    where: str = ""


# --- data concepts -------------------------------------------------------------------


class DataField(_Strict):
    name: str = Field(pattern=SNAKE_PATTERN)
    type: Literal["text", "date", "number"]
    required: bool
    description: str
    classes: list[str] = []
    references: str | None = Field(default=None, pattern=FIELD_REF_PATTERN)


class ValidationRule(_Strict):
    id: str = Field(pattern=r"^DV-[A-Z]{3}-\d{2}$")
    dimension: Literal[
        "completeness", "validity", "consistency", "uniqueness", "reasonableness", "coverage"
    ]
    severity: Literal["INFO", "WARNING", "BLOCKING"]
    fields: list[str] = Field(min_length=1)
    rule: str
    action: str


class DataConceptSpec(SpecBase):
    id: str = Field(pattern=SNAKE_PATTERN)
    file_name: str
    required_for_report: bool
    grain: str
    keys: list[str]
    fields: list[DataField] = Field(min_length=1)
    validation: list[ValidationRule] = Field(min_length=1)

    def field(self, name: str) -> DataField | None:
        return next((f for f in self.fields if f.name == name), None)


# --- conventions ---------------------------------------------------------------------


class ConventionSpec(SpecBase):
    id: str = Field(pattern=r"^CV\d{2}$")
    rules: list[str] = Field(min_length=1)
    formulas: list[Formula] = []
    defaults: list[Parameter] = []
    requires: list[str] = []
    optional: list[str] = []
    uses: list[str] = []


# --- measures ------------------------------------------------------------------------

Dimension = Literal[
    "segment",
    "line",
    "entity",
    "product",
    "partner",
    "channel",
    "cause",
    "event_code",
    "currency",
    "origin_period",
    "development_period",
    "calendar_period",
    "valuation_date",
    "claim_status",
    "claim_size_class",
    "premium_type",
    "expense_type",
    "data_concept",
]


class Bases(_Strict):
    reinsurance: list[Literal["GROSS", "CEDED", "NET"]] = Field(min_length=1)
    currency: list[Literal["ORIGINAL", "FUNCTIONAL", "REPORTING"]] = Field(min_length=1)
    value: list[Literal["NOMINAL", "INFLATION_ADJUSTED"]] = Field(min_length=1)


class EdgeCase(_Strict):
    case: str
    handling: str


class TypicalRange(_Strict):
    low: float | None
    high: float | None
    note: str


class Proof(_Strict):
    path: str = Field(pattern=r"^tests/.+\.py$")
    proves: str


class MeasureSpec(SpecBase):
    id: str = Field(pattern=r"^[A-Z]{2}\d{2}$")
    unit: Literal["amount", "ratio", "count", "days", "factor", "score"]
    formula: str
    numerator: str
    denominator: str | None
    grain: str
    breakdowns: list[Dimension]
    bases: Bases
    requires: list[str] = []
    optional: list[str] = []
    uses: list[str] = []
    parameters: list[Parameter] = []
    edge_cases: list[EdgeCase] = Field(min_length=1)
    interpretation: str
    typical_range: TypicalRange
    test: Proof


# --- methods -------------------------------------------------------------------------


class Assumption(_Strict):
    statement: str
    check: str


class AlgorithmStep(_Strict):
    step: str
    formula: str = ""


class MethodOutput(_Strict):
    name: str = Field(pattern=SNAKE_PATTERN)
    description: str


class FailureMode(_Strict):
    condition: str
    action: str


class Evidence(_Strict):
    kind: Literal["fixture", "benchmark", "ground_truth", "property"]
    description: str
    tolerance: str


class MethodSpec(SpecBase):
    id: str = Field(pattern=r"^MT\d{2}$")
    tier: Literal["A", "B", "C"]
    requires: list[str] = Field(min_length=1)
    optional: list[str] = []
    uses: list[str] = []
    assumptions: list[Assumption]
    parameters: list[Parameter]
    algorithm: list[AlgorithmStep] = Field(min_length=1)
    outputs: list[MethodOutput] = Field(min_length=1)
    diagnostics: list[str]
    failure_modes: list[FailureMode] = Field(min_length=1)
    validation: list[Evidence] = Field(min_length=1)
    references: list[str] = []


# --- modules -------------------------------------------------------------------------


class ModuleSpec(SpecBase):
    id: str = Field(pattern=r"^M\d{2}$")
    phase: int
    question: str
    required_all: list[str] = []
    required_any: list[str] = []
    optional: list[str] = []
    measures: list[str]
    methods: list[str]
    skip_reason: str = Field(min_length=1)


# --- aliases -------------------------------------------------------------------------


class ColumnAliasEntry(_Strict):
    field: str = Field(pattern=SNAKE_PATTERN)
    concepts: list[str] = Field(min_length=1)
    aliases: list[str] = Field(min_length=1)


class PersonalDataEntry(_Strict):
    kind: str = Field(pattern=SNAKE_PATTERN)
    aliases: list[str] = Field(min_length=1)


class ColumnAliasSpec(SpecBase):
    id: str = Field(pattern=r"^AL\d{2}$")
    columns: list[ColumnAliasEntry] = Field(min_length=1)
    personal_data: list[PersonalDataEntry] = Field(min_length=1)


class ValueAliasEntry(_Strict):
    field: str = Field(pattern=SNAKE_PATTERN)
    concepts: list[str] = Field(min_length=1)
    classes: dict[str, list[str]] = Field(min_length=1)


class ValueAliasSpec(SpecBase):
    id: str = Field(pattern=r"^AL\d{2}$")
    values: list[ValueAliasEntry] = Field(min_length=1)


# --- report --------------------------------------------------------------------------


class FindingEvidence(_Strict):
    section: str = Field(pattern=r"^[a-z][a-z0-9-]*$")  # report section the sentence links to
    files: list[str] = []  # output files in the run folder that hold the numbers
    specs: list[str] = []  # spec IDs the evidence rests on


class FindingRule(_Strict):
    id: str = Field(pattern=r"^KF\d{2}$")
    title: str = Field(min_length=1)
    scope: Literal["run", "segment", "line"]
    priority: int = Field(ge=0)  # lower first
    condition: str = Field(min_length=1)  # clauses `fact op fact-or-number` joined by `and`
    template: str = Field(min_length=1)  # `{fact}` placeholders, formatted by the fact's kind
    evidence: FindingEvidence
    banner: bool = False  # also shown at the top of the cover and the analytic pages


class FindingRulesSpec(SpecBase):
    id: str = Field(pattern=r"^RP\d{2}$")
    rules: list[FindingRule] = Field(min_length=1)


AnySpec = (
    DataConceptSpec
    | ConventionSpec
    | MeasureSpec
    | MethodSpec
    | ModuleSpec
    | ColumnAliasSpec
    | ValueAliasSpec
    | FindingRulesSpec
)
