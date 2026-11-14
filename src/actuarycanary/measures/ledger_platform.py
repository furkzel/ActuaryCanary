"""The platform's side of the ledger reconciliation (FN01, CV12, record 0422): for each account
class the measure it is compared with, on the platform's own grain and conversions, as one amount
per entity and month end.

`LINKS` is the table of the links, one place, so that a link can be read and tested. A flow is
the amount booked in the month (premiums at the rate of the booking date, claim flows at the
average rate of their month, CV01), a stock the amount at the month end (at the period-end rate).
The basis is GROSS except for the class RI. A class whose feed is not loaded, or whose figure
cannot be built, has no side: it is "not reconciled" and the reason says why.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from actuarycanary.convert.bases import BasisUnavailableError, ReinsuranceBasis, ValueBasis
from actuarycanary.convert.currency import Rule, convert
from actuarycanary.convert.market import ConversionError
from actuarycanary.measures.claim_amounts import monthly_ends
from actuarycanary.measures.claim_base import amounts_at, flows, header, left_out
from actuarycanary.measures.expense_measures import EXPENSES, _expense_rows
from actuarycanary.measures.model import Basis, CurrencyView, MeasureInputs, MeasureRequest
from actuarycanary.measures.premium_measures import (
    PREMIUMS,
    settings_for,
    transactions_with_policies,
)
from actuarycanary.structures.periods import Period, month_end, month_index
from actuarycanary.structures.premium import PremiumError, unearned_premium

POLICIES = "policies"
VALUATIONS = "claim_valuations"
RI_TYPES = ("CEDED_PREMIUM", "RI_COMMISSION")
_REQUEST = MeasureRequest(("entity", "calendar_period"), Period.MONTH)
_CEDED = Basis(ReinsuranceBasis.CEDED, CurrencyView.REPORTING, ValueBasis.NOMINAL)
_GROSS = Basis(ReinsuranceBasis.GROSS, CurrencyView.REPORTING, ValueBasis.NOMINAL)
_GROSS_ORIGINAL = Basis(ReinsuranceBasis.GROSS, CurrencyView.ORIGINAL, ValueBasis.NOMINAL)
ENTITY = "entity"
MONTH = "period"
AMOUNT = "amount"
FOREIGN = "foreign"


@dataclass(frozen=True)
class Side:
    """One class's platform amounts: `frame` (entity, period, amount, and `foreign`, the size of
    the part of `amount` that came from rows in another currency than the reporting currency; one
    row per entity and month end of the feed's own range, zero where it has no row) or None with
    the reason."""

    frame: pl.DataFrame | None  # entity, period, amount, foreign
    reason: str = ""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Link:
    account_class: str
    measure: str  # what the reader is told the figure is
    kind: str  # "flow" or "stock"
    needs: tuple[str, ...]  # feeds that must be loaded
    basis: str
    source: "Callable[[MeasureInputs], Side]" = field(repr=False, compare=False)


def _flow_grid(rows: pl.DataFrame, first: date, last: date) -> pl.DataFrame:
    """`rows` (entity, period, amount) with a zero for every entity and month end of the range
    `first` to `last` that has none."""
    months = [month_end(m) for m in range(month_index(first), month_index(last) + 1)]
    entities = rows.select(ENTITY).unique().sort(ENTITY)
    grid = entities.join(pl.DataFrame({MONTH: months}, schema={MONTH: pl.Date}), how="cross")
    return (
        grid.join(rows, on=[ENTITY, MONTH], how="left")
        .with_columns(pl.col(AMOUNT, FOREIGN).fill_null(0.0))
        .sort(ENTITY, MONTH)
    )


def _by_month(rows: pl.DataFrame, date_column: str, foreign: pl.Expr) -> pl.DataFrame:
    """Entity, month end, amount and the absolute amount of the rows `foreign` marks."""
    return (
        rows.filter(pl.col(ENTITY).is_not_null() & (pl.col(ENTITY) != "UNKNOWN"))
        .with_columns(pl.col(date_column).dt.month_end().alias(MONTH))
        .group_by(ENTITY, MONTH)
        .agg(
            pl.col(AMOUNT).sum(),
            pl.col(AMOUNT).abs().filter(foreign.fill_null(False)).sum().alias(FOREIGN),
        )
    )


def _range(frame: pl.DataFrame, column: str, cut_off: date) -> tuple[date, date] | None:
    inside = frame.filter(pl.col(column) <= cut_off)[column]
    first, last = inside.min(), inside.max()
    if not isinstance(first, date) or not isinstance(last, date):
        return None
    return first, last


def _premium_flows(inputs: MeasureInputs, *, types: tuple[str, ...] | None) -> Side:
    if not inputs.has(POLICIES):
        return Side(None, "premiums need policies for the entity of each transaction")
    try:
        rows, notes = transactions_with_policies(
            inputs,
            _REQUEST,
            ReinsuranceBasis.GROSS,
            **({} if types is None else {"transaction_types": types}),
        )
    except PremiumError as error:
        return Side(None, str(error))
    rows = rows.rename({"amount": AMOUNT})
    covered = _range(inputs.feeds[PREMIUMS], "booking_date", inputs.cut_off)
    if covered is None or rows.height == 0:
        what = "premium transactions" if types is None else f"{', '.join(types)} rows"
        return Side(None, f"no {what} up to the cut-off")
    marked = (pl.col("rate") != 1.0).fill_null(False)
    return Side(_flow_grid(_by_month(rows, "booking_date", marked), *covered), notes=tuple(notes))


def written_premium(inputs: MeasureInputs) -> Side:
    return _premium_flows(inputs, types=None)


def commission(inputs: MeasureInputs) -> Side:
    return _premium_flows(inputs, types=("COMMISSION",))


def _claim_flows(inputs: MeasureInputs, basis: Basis, measure: str) -> Side:
    rows, notes = flows(inputs, basis, measure)
    rows, left = left_out(rows, measure)
    entity = header(inputs, _REQUEST).select("claim_id", ENTITY)
    rows = rows.join(entity, on="claim_id", how="left").rename({"value": AMOUNT})
    covered = _range(inputs.feeds[VALUATIONS], "valuation_date", inputs.cut_off)
    if covered is None or rows.height == 0:
        return Side(None, "no claim valuations up to the cut-off")
    marked = pl.col("currency") != inputs.reporting_currency
    return Side(
        _flow_grid(_by_month(rows, "valuation_date", marked), *covered),
        notes=tuple([*notes, *left]),
    )


def claims_paid(inputs: MeasureInputs) -> Side:
    return _claim_flows(inputs, _GROSS, "paid")


def outstanding(inputs: MeasureInputs) -> Side:
    """CL02 at each month end, the amount of each claim converted at the period-end rate of
    that month end (CV01), not at the constant rate of the development view."""
    ends = monthly_ends(inputs)
    states, notes = amounts_at(inputs, _GROSS_ORIGINAL, "case_reserve", ends)
    states, left = left_out(states, "case reserve")
    entity = header(inputs, _REQUEST).select("claim_id", ENTITY)
    states = states.join(entity, on="claim_id", how="left").with_columns(
        pl.col("value").alias(AMOUNT)
    )
    done = convert(
        states,
        [AMOUNT],
        day="end",
        rule=Rule.STOCK,
        target=inputs.reporting_currency,
        market=inputs.market,
    )
    kept = done.frame.filter(pl.col("rate").is_not_null())
    extra = (
        [f"left out, no period-end rate: {done.not_converted['rows'].sum()} claim states"]
        if done.not_converted.height
        else []
    )
    marked = pl.col("currency") != inputs.reporting_currency
    return Side(
        _flow_grid(_by_month(kept, "end", marked), ends[0], ends[-1]),
        notes=tuple([*notes, *left, *extra]),
    )


def unearned(inputs: MeasureInputs) -> Side:
    """PR03 at each month end of the premium file, by entity."""
    if not inputs.has(POLICIES):
        return Side(None, "unearned premium needs policies for the entity of each transaction")
    covered = _range(inputs.feeds[PREMIUMS], "booking_date", inputs.cut_off)
    if covered is None:
        return Side(None, "no premium transactions up to the cut-off")
    settings = settings_for(inputs, _REQUEST)
    parts: list[pl.DataFrame] = []
    try:
        for m in range(month_index(covered[0]), month_index(covered[1]) + 1):
            at = month_end(m)
            result = unearned_premium(
                inputs.feeds[PREMIUMS],
                inputs.feeds[POLICIES],
                settings,
                at,
                inputs.market,
                [ENTITY],
            )
            parts.append(
                result.frame.group_by(ENTITY)
                .agg(pl.col("unearned_premium").sum().alias(AMOUNT))
                .with_columns(pl.lit(at).alias(MONTH))
            )
    except (PremiumError, ValueError) as error:
        return Side(None, str(error))
    rows = (
        pl.concat(parts)
        .filter(pl.col(ENTITY) != "UNKNOWN")
        .with_columns(pl.lit(0.0).alias(FOREIGN))
    )
    return Side(_flow_grid(rows, *covered))


def expenses(inputs: MeasureInputs) -> Side:
    types = inputs.feeds[EXPENSES]["type"].unique().to_list()
    rows, notes = _expense_rows(inputs, _REQUEST, types)
    if ENTITY not in rows.columns:
        return Side(None, "expense rows carry no entity")
    rows = rows.rename({"amount": AMOUNT})
    covered = _range(inputs.feeds[EXPENSES], "period", inputs.cut_off)
    if covered is None or rows.height == 0:
        return Side(None, "no expense rows up to the cut-off", tuple(notes))
    marked = (pl.col("rate") != 1.0).fill_null(False)
    return Side(_flow_grid(_by_month(rows, "period", marked), *covered), notes=tuple(notes))


def reinsurance_net_cost(inputs: MeasureInputs) -> Side:
    """The ceded measures (RI01 and RI02 read the same rows): ceded premium less reinsurance
    commission less ceded paid, per entity and month, on the CEDED basis (CV03)."""
    premium = _premium_flows(inputs, types=("CEDED_PREMIUM",))
    if premium.frame is None:
        return Side(None, f"ceded premium: {premium.reason}")
    commission_side = _premium_flows(inputs, types=("RI_COMMISSION",))
    paid = _claim_flows(inputs, _CEDED, "paid")
    if paid.frame is None:
        return Side(None, f"ceded paid: {paid.reason}")
    parts = [premium.frame.with_columns(pl.lit(1.0).alias("sign"))]
    if commission_side.frame is not None:
        parts.append(commission_side.frame.with_columns(pl.lit(-1.0).alias("sign")))
    parts.append(paid.frame.with_columns(pl.lit(-1.0).alias("sign")))
    both = pl.concat(parts)
    frame = (
        both.group_by(ENTITY, MONTH)
        .agg((pl.col(AMOUNT) * pl.col("sign")).sum().alias(AMOUNT), pl.col(FOREIGN).sum())
        .sort(ENTITY, MONTH)
    )
    notes = (*premium.notes, *paid.notes)
    return Side(frame, notes=notes)


LINKS: dict[str, Link] = {
    link.account_class: link
    for link in (
        Link(
            "PREMIUM",
            "PR01 written premium",
            "flow",
            (PREMIUMS, POLICIES),
            "GROSS",
            written_premium,
        ),
        Link(
            "CLAIMS_PAID", "CL01 paid flows", "flow", (VALUATIONS, "claims"), "GROSS", claims_paid
        ),
        Link(
            "OUTSTANDING",
            "CL02 case reserve",
            "stock",
            (VALUATIONS, "claims"),
            "GROSS",
            outstanding,
        ),
        Link("UPR", "PR03 unearned premium", "stock", (PREMIUMS, POLICIES), "GROSS", unearned),
        Link(
            "COMMISSION",
            "COMMISSION premium rows",
            "flow",
            (PREMIUMS, POLICIES),
            "GROSS",
            commission,
        ),
        Link("EXPENSE", "expenses feed", "flow", (EXPENSES,), "GROSS", expenses),
        Link(
            "RI",
            "ceded premium less RI commission less ceded paid",
            "flow",
            (PREMIUMS, POLICIES, VALUATIONS, "claims"),
            "CEDED",
            reinsurance_net_cost,
        ),
    )
}


def platform_side(inputs: MeasureInputs, account_class: str) -> Side:
    """The platform amounts of one class, or why there are none."""
    link = LINKS[account_class]
    absent = [c for c in link.needs if not inputs.has(c)]
    if absent:
        return Side(None, f"{' and '.join(absent)} not loaded")
    try:
        return link.source(inputs)
    except (BasisUnavailableError, ConversionError, PremiumError) as error:
        return Side(None, str(error))  # a figure that cannot be built says why, it is no gap
