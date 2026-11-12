"""Treaty terms of a reinsurance programme (MT21, CV09): the rows of `reinsurance_treaties`
grouped into sections, the stage of each section in the inuring order, and the rows left out.

A section is one treaty for one contract period: the rows of one treaty_id and inception date
whose terms agree (the treaties feed has one row per line with the same terms). A treaty whose
rows for a period disagree on terms gives one section per set of terms. Decision 0400.
"""

from dataclasses import dataclass, field, fields, replace
from datetime import date
from typing import Any

import polars as pl

QUOTA_SHARE = "QUOTA_SHARE"
SURPLUS = "SURPLUS"
EXCESS_OF_LOSS = "EXCESS_OF_LOSS"
STOP_LOSS = "STOP_LOSS"
FACULTATIVE = "FACULTATIVE"
TREATY_TYPES = (QUOTA_SHARE, SURPLUS, EXCESS_OF_LOSS, STOP_LOSS, FACULTATIVE)
PROPORTIONAL_TYPES = (QUOTA_SHARE, SURPLUS, FACULTATIVE)

LOSSES_OCCURRING = "LOSSES_OCCURRING"
RISKS_ATTACHING = "RISKS_ATTACHING"
RISK, EVENT, AGGREGATE = "RISK", "EVENT", "AGGREGATE"

# the inuring order of CV09 (record 0604): each stage works on what the stages before it leave;
# the sections of one stage work side by side on the same amounts (decision 0400)
STAGES = ("FACULTATIVE", "SURPLUS", "QUOTA_SHARE", "RISK_XL", "EVENT_XL", "AGGREGATE")

TERM_COLUMNS = (
    "cession_share",
    "retention",
    "limit",
    "number_of_lines",
    "aggregate_deductible",
    "aggregate_limit",
    "reinstatements",
    "reinstatement_rate",
    "placed_share",
    "premium_rate",
    "ceding_commission",
)
TEXT_COLUMNS = (
    "attachment_basis",
    "loss_basis",
    "segment",
    "entity",
    "currency",
    "index_series",
)


@dataclass(frozen=True)
class Section:
    """One treaty for one contract period, with the scope and terms of CV09."""

    treaty_id: str
    treaty_type: str
    inception: date
    expiry: date
    currency: str
    attachment_basis: str = LOSSES_OCCURRING
    loss_basis: str = RISK
    lines: frozenset[str] | None = None  # None: every line
    segment: str | None = None
    entity: str | None = None
    cession_share: float | None = None
    retention: float | None = None
    limit: float | None = None
    number_of_lines: float | None = None
    aggregate_deductible: float | None = None
    aggregate_limit: float | None = None
    reinstatements: float | None = None
    reinstatement_rate: float | None = None
    placed_share: float = 1.0
    premium_rate: float | None = None
    ceding_commission: float | None = None
    index_series: str | None = None
    labels: tuple[str, ...] = field(default=())

    @property
    def key(self) -> tuple[str, date]:
        return (self.treaty_id, self.inception)

    @property
    def stage(self) -> str:
        if self.treaty_type == EXCESS_OF_LOSS:
            return {EVENT: "EVENT_XL", AGGREGATE: "AGGREGATE"}.get(self.loss_basis, "RISK_XL")
        if self.treaty_type == STOP_LOSS:
            return "AGGREGATE"
        return self.treaty_type

    @property
    def is_proportional(self) -> bool:
        return self.treaty_type in PROPORTIONAL_TYPES

    @property
    def has_aggregate_terms(self) -> bool:
        return (
            self.aggregate_deductible is not None
            or self.aggregate_limit is not None
            or self.reinstatements is not None
        )

    @property
    def effective_aggregate_limit(self) -> float | None:
        """The annual aggregate limit: given, or limit times (1 + reinstatements) when the
        number of reinstatements is given; None means unlimited (treaties spec)."""
        if self.aggregate_limit is not None:
            return self.aggregate_limit
        if self.reinstatements is not None and self.limit is not None:
            return self.limit * (1.0 + self.reinstatements)
        return None

    def label(self, text: str) -> "Section":
        return self if text in self.labels else replace(self, labels=(*self.labels, text))


@dataclass(frozen=True)
class Excluded:
    treaty_id: str
    inception: date | None
    reason: str


def _missing_terms(kind: str, row: dict[str, Any]) -> str | None:
    """DV-RTY-05: the terms each type needs."""
    if kind == QUOTA_SHARE and row.get("cession_share") is None:
        return "quota share without cession_share (DV-RTY-05)"
    if kind == SURPLUS and (row.get("retention") is None or row.get("number_of_lines") is None):
        return "surplus without retention or number_of_lines (DV-RTY-05)"
    if kind in (EXCESS_OF_LOSS, STOP_LOSS) and row.get("retention") is None:
        return f"{kind.lower().replace('_', ' ')} without retention (DV-RTY-05)"
    return None


def _invalid_terms(row: dict[str, Any]) -> str | None:
    """DV-RTY-06 and DV-RTY-07: shares between zero and one, terms not negative."""
    for name in ("cession_share", "placed_share", "ceding_commission"):
        value = row.get(name)
        if value is not None and not 0.0 <= value <= 1.0:
            return f"{name} outside 0 to 1 (DV-RTY-06)"
    for name in ("retention", "limit", "aggregate_deductible", "aggregate_limit", "reinstatements"):
        value = row.get(name)
        if value is not None and value < 0:
            return f"{name} negative (DV-RTY-07)"
    lines = row.get("number_of_lines")
    if lines is not None and lines <= 0:
        return "number_of_lines not positive (DV-RTY-07)"
    return None


def _reason(row: dict[str, Any]) -> str | None:
    for name in ("treaty_id", "treaty_type", "inception_date", "expiry_date", "currency"):
        if row.get(name) is None:
            return f"{name} missing (DV-RTY-01)"
    kind = row["treaty_type"]
    if kind not in TREATY_TYPES:
        return f"treaty type {kind} not recognised (DV-RTY-02)"
    if row["expiry_date"] <= row["inception_date"]:
        return "expiry_date not after inception_date (DV-RTY-03)"
    return _missing_terms(kind, row) or _invalid_terms(row)


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def sections_from_frame(treaties: pl.DataFrame) -> tuple[list[Section], list[Excluded]]:
    """The sections of a programme and the rows left out, with the reason of each."""
    excluded: list[Excluded] = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in treaties.to_dicts():
        reason = _reason(row)
        if reason is not None:
            excluded.append(Excluded(str(row.get("treaty_id")), row.get("inception_date"), reason))
            continue
        terms = tuple(_number(row.get(c)) for c in TERM_COLUMNS)
        text = tuple(row.get(c) for c in TEXT_COLUMNS)
        key = (row["treaty_id"], row["treaty_type"], row["inception_date"], row["expiry_date"])
        groups.setdefault((*key, terms, text), []).append(row)
    sections: list[Section] = []
    for (treaty_id, kind, inception, expiry, terms, text), rows in groups.items():
        values = dict(zip(TERM_COLUMNS, terms, strict=True))
        texts = dict(zip(TEXT_COLUMNS, text, strict=True))
        lines = [r.get("line") for r in rows]
        default_basis = AGGREGATE if kind == STOP_LOSS else RISK
        placed = values.pop("placed_share")
        sections.append(
            Section(
                treaty_id=str(treaty_id),
                treaty_type=kind,
                inception=inception,
                expiry=expiry,
                currency=str(texts["currency"]),
                attachment_basis=texts["attachment_basis"] or LOSSES_OCCURRING,
                loss_basis=texts["loss_basis"] or default_basis,
                lines=None if any(x is None for x in lines) else frozenset(map(str, lines)),
                segment=texts["segment"],
                entity=texts["entity"],
                index_series=texts["index_series"],
                placed_share=1.0 if placed is None else placed,
                **values,
            )
        )
    sections.sort(key=lambda s: (STAGES.index(s.stage), s.treaty_id, s.inception))
    return sections, excluded


def section_frame(sections: list[Section]) -> pl.DataFrame:
    """One row per section with its terms (for the treaty table of M08)."""
    names = [f.name for f in fields(Section) if f.name not in ("lines", "labels")]
    rows = []
    for s in sections:
        row = {n: getattr(s, n) for n in names}
        row["lines"] = "" if s.lines is None else ", ".join(sorted(s.lines))
        row["stage"] = s.stage
        row["labels"] = "; ".join(s.labels)
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)
