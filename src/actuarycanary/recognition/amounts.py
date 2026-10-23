"""Are the claim amounts cumulative to date or incremental per period? (record 0223)

Cumulative paid never falls from one valuation of a claim to the next (DV-CLV-07), so a share
of falls among the amounts that follow a positive amount is the sign of increments: the payment
of one month is followed by a smaller or no payment the next. The values are read from a
sample of claims, because only the claim's own rows in date order tell.
"""

from dataclasses import dataclass, replace

import polars as pl

from actuarycanary.canonical.amounts import INCREMENTAL, TO_DATE
from actuarycanary.canonical.dates import parse_dates
from actuarycanary.canonical.feeds import as_text
from actuarycanary.io.excel import SOURCE_ROW, RawTable
from actuarycanary.recognition.tables import Source, TableRecognition

CONCEPT = "claim_valuations"
SAMPLE_CLAIMS = 3000  # claims read, with all their rows
MIN_PAIRS = 20  # pairs of consecutive amounts needed before the values decide
FALL_SHARE = 0.20  # cumulative data has a few falls (faults), increments many


@dataclass(frozen=True)
class AmountsEvidence:
    pairs: int  # consecutive amounts of one claim where the earlier one is positive
    falls: int  # of those, where the later one is lower

    @property
    def share(self) -> float:
        return self.falls / self.pairs if self.pairs else 0.0

    @property
    def incremental(self) -> bool:
        return self.pairs >= MIN_PAIRS and self.share >= FALL_SHARE

    def describe(self) -> str:
        if self.pairs < MIN_PAIRS:
            return "too few repeated amounts to tell; read as cumulative"
        text = f"{self.falls} of {self.pairs} amounts that follow a positive amount are lower"
        if self.incremental:
            return f"{text}: cumulative amounts do not fall, so these are per period"
        return f"{text}: cumulative"


def measure(frame: pl.DataFrame) -> AmountsEvidence:
    """Falls among consecutive paid amounts of claims; `frame` has claim_id, valuation_date and
    paid_to_date typed (and the source row for a stable order)."""
    order = ["claim_id", "valuation_date", *([SOURCE_ROW] if SOURCE_ROW in frame.columns else [])]
    rows = frame.filter(pl.col("paid_to_date").is_not_null()).sort(order)
    pairs = rows.with_columns(pl.col("paid_to_date").shift(1).over("claim_id").alias("_previous"))
    pairs = pairs.filter(pl.col("_previous") > 0)
    return AmountsEvidence(
        pairs.height, pairs.filter(pl.col("paid_to_date") < pl.col("_previous")).height
    )


def _header(rec: TableRecognition, field: str) -> str | None:
    return next((m.source for m in rec.mappings if m.used and m.field == field), None)


def sample_values(table: RawTable, rec: TableRecognition) -> pl.DataFrame | None:
    """claim_id, valuation_date and paid_to_date of a sample of claims, typed; None when the
    sheet has no such columns."""
    claim, day, paid = (_header(rec, f) for f in ("claim_id", "valuation_date", "paid_to_date"))
    if claim is None or day is None or paid is None:
        return None
    frame = table.frame
    ids = as_text(frame[claim]).str.strip_chars()
    keep = ids.drop_nulls().unique(maintain_order=True).head(SAMPLE_CLAIMS)
    chosen = frame.filter(ids.is_in(keep.implode()))
    columns: dict[str, pl.Series] = {
        "claim_id": as_text(chosen[claim]).str.strip_chars().alias("claim_id"),
        "valuation_date": parse_dates(chosen[day]).values.alias("valuation_date"),
        "paid_to_date": chosen[paid].cast(pl.Float64, strict=False).alias("paid_to_date"),
    }
    if SOURCE_ROW in chosen.columns:
        columns[SOURCE_ROW] = chosen[SOURCE_ROW]
    return pl.DataFrame(columns).drop_nulls(["claim_id", "valuation_date"])


def detect_amounts(rec: TableRecognition, table: RawTable) -> TableRecognition:
    """The recognition with its amounts kind: the one a saved profile or the user decided, else
    the one the values show. A sheet in the canonical layout whose amounts are incremental is
    put up for confirmation like any other proposal."""
    if rec.concept != CONCEPT:
        return replace(rec, amounts=TO_DATE, amounts_note="", amounts_decided=False)
    if rec.amounts_decided:
        return rec
    values = sample_values(table, rec)
    if values is None:
        return replace(rec, amounts=TO_DATE, amounts_note="")
    evidence = measure(values)
    if not evidence.incremental:
        return replace(rec, amounts=TO_DATE, amounts_note=evidence.describe())
    source = Source.AUTOMATIC if rec.source is Source.CANONICAL else rec.source
    return replace(rec, amounts=INCREMENTAL, amounts_note=evidence.describe(), source=source)
