"""M09 Expenses: the table of the module beside its measures (EX01 to EX05): expenses by type,
level and month, nominal and at value-date prices. Every amount stays at the level it was
booked: a row without a line or a segment is shown as such and never spread over lines."""

from dataclasses import dataclass

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import ConversionError
from actuarycanary.measures.expense_measures import EXPENSES, LEVELS
from actuarycanary.measures.model import Basis, CurrencyView, MeasureInputs, MeasureRequest
from actuarycanary.measures.unit_cost_measures import valued_expenses
from actuarycanary.structures.periods import Period

NOMINAL = "amount"
AT_VALUE_DATE = "amount_at_value_date_prices"
COLUMNS = ("month", "type", "entity", "segment", "line", "currency", "rows", NOMINAL, AT_VALUE_DATE)


@dataclass(frozen=True)
class ExpenseTable:
    frame: pl.DataFrame  # COLUMNS; an empty entity, segment or line means: not allocated
    notes: tuple[str, ...]  # conversions, rows left out, why a column is empty

    @property
    def unallocated(self) -> pl.DataFrame:
        """The rows that carry no line: shown at the level they were booked."""
        return self.frame.filter(pl.col("line").is_null())


def _by_level(rows: pl.DataFrame, value: str) -> pl.DataFrame:
    levels = [pl.col(c) if c in rows.columns else pl.lit(None, pl.String).alias(c) for c in LEVELS]
    return (
        rows.with_columns(*levels, pl.col("period").dt.month_end().alias("month"))
        .group_by("month", "type", "entity", "segment", "line", "currency", maintain_order=True)
        .agg(pl.col("amount").sum().alias(value), pl.len().cast(pl.Int64).alias("rows"))
    )


def expense_table(
    inputs: MeasureInputs, view: CurrencyView = CurrencyView.REPORTING
) -> ExpenseTable:
    """Expenses up to the cut-off by month, type and the level they were booked at, in the
    currency view of the run; the column at value-date prices needs the reporting currency and
    a price index (CV02) and is empty otherwise, with the reason in the notes."""
    types = inputs.feeds[EXPENSES]["type"].drop_nulls().unique().sort().to_list()

    def request(value: ValueBasis) -> MeasureRequest:
        return MeasureRequest((), Period.MONTH, Basis(ReinsuranceBasis.GROSS, view, value))

    rows, notes = valued_expenses(inputs, request(ValueBasis.NOMINAL), types)
    keys = ["month", "type", "entity", "segment", "line", "currency"]
    frame = _by_level(rows, NOMINAL)
    try:
        restated, more = valued_expenses(inputs, request(ValueBasis.INFLATION_ADJUSTED), types)
        priced = _by_level(restated, AT_VALUE_DATE).drop("rows")
        frame = frame.join(priced, on=keys, how="left", nulls_equal=True)
        notes += [n for n in more if n not in notes]
    except ConversionError as error:
        frame = frame.with_columns(pl.lit(None, pl.Float64).alias(AT_VALUE_DATE))
        notes.append(f"no amounts at value-date prices: {error}")
    frame = frame.with_columns(pl.col(NOMINAL, AT_VALUE_DATE).round(2)).select(COLUMNS)
    return ExpenseTable(frame.sort(keys, nulls_last=True), tuple(notes))
