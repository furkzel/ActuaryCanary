"""M07 Recoveries: the tables of the module beside its measures (RC01 to RC04): the recovery
flows per claim, type and month with their source, and the reconciliation of recovery
transactions with the to-date fields of claim valuations (DV-RCV-08, decision 0203)."""

from dataclasses import dataclass

import polars as pl

from actuarycanary.canonical.recoveries import (
    DERIVED_COLUMN,
    TRANSACTIONS,
    recovery_differences,
    to_date_fields,
)
from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.measures.model import REF, MeasureInputs
from actuarycanary.measures.recovery_measures import VALUATIONS, recoveries_of

FLOW_COLUMNS = ("claim_id", "type", "month", "currency", "amount", "bookings", DERIVED_COLUMN)
RECONCILIATION_COLUMNS = ("claim_id", "type", "valuation_date", "booked", "to_date", "difference")
NOT_RECONCILED_DERIVED = (
    "the flows are derived from the to-date fields, so there is nothing to reconcile them with"
)
NOT_RECONCILED_NO_FIELDS = (
    "claim valuations carry no to-date recovery column to reconcile the transactions with"
)


@dataclass(frozen=True)
class RecoveryTables:
    source: str  # "transactions", "derived" or "none"
    note: str  # one sentence on the source of the figures
    flows: pl.DataFrame  # FLOW_COLUMNS: amounts in original currency per claim, type and month
    reconciliation: pl.DataFrame  # RECONCILIATION_COLUMNS: one row per difference
    reconciliation_note: str  # why there is no reconciliation, or what was compared

    @property
    def available(self) -> bool:
        return self.source != "none"


def recovery_tables(inputs: MeasureInputs) -> RecoveryTables:
    """The flows and the reconciliation of the run, up to the cut-off."""
    recoveries = recoveries_of(inputs)
    flows = (
        recoveries.frame.with_columns(pl.col("booking_date").dt.month_end().alias("month"))
        .group_by("claim_id", "type", "month", "currency", DERIVED_COLUMN)
        .agg(pl.col("amount").sum().round(2), pl.len().cast(pl.Int64).alias("bookings"))
        .select(FLOW_COLUMNS)
        .sort("claim_id", "month", "type", "currency")
    )
    valuations = inputs.feeds[VALUATIONS].filter(pl.col("valuation_date") <= inputs.cut_off)
    empty = pl.DataFrame(
        schema={
            "claim_id": pl.String,
            "type": pl.String,
            "valuation_date": pl.Date,
            "booked": pl.Float64,
            "to_date": pl.Float64,
            "difference": pl.Float64,
        }
    )
    if recoveries.source != TRANSACTIONS:
        note = NOT_RECONCILED_DERIVED if recoveries.available else recoveries.note
        return RecoveryTables(recoveries.source, recoveries.note, flows, empty, note)
    fields = to_date_fields(valuations)
    if not fields:
        return RecoveryTables(
            recoveries.source, recoveries.note, flows, empty, NOT_RECONCILED_NO_FIELDS
        )
    drop = [c for c in (*SOURCE_COLUMNS, REF) if c in recoveries.frame.columns]
    differences = recovery_differences(recoveries.frame.drop(drop), valuations)
    differences = differences.select(RECONCILIATION_COLUMNS).with_columns(
        pl.col("booked", "to_date", "difference").round(2)
    )
    compared = sum(int(valuations[name].is_not_null().sum()) for name in fields.values())
    note = (
        f"transactions accumulated to each valuation date against {' and '.join(fields.values())}: "
        f"{differences.height} of {compared} valuations differ; the transactions are used"
    )
    return RecoveryTables(recoveries.source, recoveries.note, flows, differences, note)
