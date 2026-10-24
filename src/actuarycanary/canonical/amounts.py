"""Cumulative or incremental claim amounts (record 0223).

The canonical claim valuations hold amounts cumulative to the valuation date (CV04). A file may
instead hold what was paid, recovered or allocated in each period; recognition detects that
from the values or the user says so, and `accumulate` adds the amounts up per claim.
"""

import polars as pl

from actuarycanary.io.excel import SOURCE_ROW

TO_DATE = "to_date"  # amounts are cumulative to the valuation date, as the specification says
INCREMENTAL = "incremental"  # amounts are those of the period of the row
AMOUNT_KINDS = (TO_DATE, INCREMENTAL)
# The fields of claim_valuations that are cumulative by definition; reserves are stocks.
ACCUMULATED_FIELDS = (
    "paid_to_date",
    "subrogation_to_date",
    "salvage_to_date",
    "expense_allocated_to_date",
    "ceded_paid_to_date",
)
RULE = "CV07-INCREMENTAL"  # finding written when increments were accumulated


def accumulate(frame: pl.DataFrame) -> pl.DataFrame:
    """The cumulative fields summed per claim in valuation order. An empty amount stays empty
    on its own row and adds nothing to the rows after it."""
    fields = [f for f in ACCUMULATED_FIELDS if f in frame.columns]
    has_row = SOURCE_ROW in frame.columns
    order = ["claim_id", "valuation_date", *([SOURCE_ROW] if has_row else [])]
    total = [
        pl.when(pl.col(f).is_null())
        .then(None)
        .otherwise(pl.col(f).fill_null(0.0).cum_sum().over("claim_id"))
        .alias(f)
        for f in fields
    ]
    result = frame.sort(order).with_columns(total)
    return result.sort(SOURCE_ROW) if has_row else result
