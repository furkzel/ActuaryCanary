"""Earned premium, unearned premium and earned exposure by period (PR02, PR03, CV04).

Premium transactions are earned evenly by day (pro rata temporis) over the interval from
their effective date, or the policy start if later, to the policy end. Earning intervals are
half open, so a policy from 2024-01-01 to 2025-01-01 covers 366 days. Exposure counts the days
of cover of the policy, clipped at cancellation, times exposure units over 365.25.

Each transaction is converted at the rate of its booking date and restated from its booking
month on the inflation-adjusted basis, then earned (CV01, CV02); net is gross minus ceded
per transaction before any aggregation (CV03).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from actuarycanary.canonical.feeds import Finding, finding
from actuarycanary.convert.bases import BasisUnavailableError, ReinsuranceBasis, ValueBasis
from actuarycanary.convert.currency import MAX_LOOKBACK_DAYS, Rule, convert
from actuarycanary.convert.inflation import restatement_factors
from actuarycanary.convert.market import ConversionError, MarketData, month_of
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import Period, month_end, month_index, period_label

WRITTEN_TYPES = ("WRITTEN", "ENDORSEMENT", "CANCELLATION", "REFUND")  # PR01
CEDED_TYPE = "CEDED_PREMIUM"
DAYS_PER_YEAR = 365.25  # CV04 days_per_year
UNKNOWN = "UNKNOWN"
GROUP_BY = ("segment", "line")  # policy attributes that earned values are grouped by


class PremiumError(Exception):
    """The premium structure cannot be built from the data given."""


class PremiumSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: Period = Period.MONTH
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    cut_off: date | None = None  # None: the latest booking date of the premiums
    reinsurance_basis: ReinsuranceBasis = ReinsuranceBasis.GROSS
    value_basis: ValueBasis = ValueBasis.NOMINAL
    value_date: date | None = None  # CV02; None: the cut-off
    price_index: str = "CPI_TR"
    reporting_currency: str | None = None  # None: original currency, one row per currency
    # Transaction types earned instead of the written types of the basis (for example
    # COMMISSION, EX01, or RI_COMMISSION, RI02); gross only, amounts as given.
    transaction_types: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PremiumStructure:
    """`frame` is one row per segment, line, currency and period; `not_converted` the
    original-currency totals of the transactions left out because no rate applied."""

    frame: pl.DataFrame
    not_converted: pl.DataFrame
    findings: tuple[Finding, ...] = ()
    cut_off: date | None = None
    flagged: dict[str, int] = field(default_factory=dict)


def _first_day(month: pl.Expr) -> pl.Expr:
    return pl.date(month // 12, month % 12 + 1, 1)


def _period_number(day: pl.Expr, settings: PremiumSettings) -> pl.Expr:
    offset = settings.fiscal_year_start_month - 1
    year, month = day.dt.year().cast(pl.Int64), day.dt.month().cast(pl.Int64)
    return (year * 12 + month - 1 - offset) // settings.period.months


def _label(frame: pl.DataFrame, settings: PremiumSettings) -> pl.DataFrame:
    """Add the period label and sort by period."""
    offset = settings.fiscal_year_start_month - 1
    length = settings.period.months
    labels = {
        n: period_label(n * length + offset, settings.period, settings.fiscal_year_start_month)
        for n in frame["period_number"].unique().to_list()
    }
    return frame.with_columns(
        pl.col("period_number").replace_strict(labels, return_dtype=pl.String).alias("period")
    )


def _expand(intervals: pl.DataFrame, settings: PremiumSettings, cut_off: date) -> pl.DataFrame:
    """One row per transaction and period of the earning interval up to the cut-off, with
    the share of the transaction earned in that period (`share`)."""
    offset = settings.fiscal_year_start_month - 1
    length = settings.period.months
    total = (pl.col("end") - pl.col("begin")).dt.total_days()
    last = pl.min_horizontal(pl.col("end") - pl.duration(days=1), pl.lit(cut_off))
    first_n = _period_number(pl.col("begin"), settings)
    last_n = pl.when(total <= 0).then(first_n).otherwise(_period_number(last, settings))
    expanded = (
        intervals.with_columns(
            first_n.alias("_first"), last_n.alias("_last"), total.alias("_total")
        )
        .filter((pl.col("_last") >= pl.col("_first")) & (pl.col("begin") <= cut_off))
        .with_columns(pl.int_ranges(pl.col("_first"), pl.col("_last") + 1).alias("period_number"))
        .explode("period_number")
    )
    start = _first_day(pl.col("period_number") * length + offset)
    stop = _first_day(pl.col("period_number") * length + offset + length)
    known_until = pl.lit(
        cut_off + timedelta(days=1)
    )  # a period still running counts to the cut-off
    overlap = (
        (
            pl.min_horizontal(pl.col("end"), stop, known_until)
            - pl.max_horizontal(pl.col("begin"), start)
        )
        .dt.total_days()
        .clip(lower_bound=0)
    )
    share = pl.when(pl.col("_total") <= 0).then(1.0).otherwise(overlap / pl.col("_total"))
    return expanded.with_columns(share.alias("share")).drop("_first", "_last", "_total")


def _transactions(premiums: pl.DataFrame, settings: PremiumSettings) -> pl.DataFrame:
    """Signed amounts of the premium transactions on the reinsurance basis (CV03)."""
    basis = settings.reinsurance_basis
    if settings.transaction_types is not None:
        sign = {t: 1.0 for t in settings.transaction_types}
    else:
        sign = _signs(premiums, basis)
    effective = (
        pl.col("effective_date").fill_null(pl.col("booking_date"))
        if "effective_date" in premiums.columns
        else pl.col("booking_date")
    )
    return premiums.filter(pl.col("type").is_in(list(sign))).with_columns(
        (pl.col("amount") * pl.col("type").replace_strict(sign, return_dtype=pl.Float64)).alias(
            "amount"
        ),
        effective.alias("effective_date"),
    )


def _signs(premiums: pl.DataFrame, basis: ReinsuranceBasis) -> dict[str, float]:
    has_ceded = (premiums["type"] == CEDED_TYPE).any()
    if basis is not ReinsuranceBasis.GROSS and not has_ceded:
        raise BasisUnavailableError(
            f"premiums on the {basis.value} basis need CEDED_PREMIUM rows, which the premium "
            "transactions do not have; the basis is not set equal to gross (CV03)"
        )
    return {
        ReinsuranceBasis.GROSS: {t: 1.0 for t in WRITTEN_TYPES},
        ReinsuranceBasis.CEDED: {CEDED_TYPE: 1.0},
        ReinsuranceBasis.NET: {**{t: 1.0 for t in WRITTEN_TYPES}, CEDED_TYPE: -1.0},
    }[basis]


def _nothing_left(amount: str = "amount") -> pl.DataFrame:
    schema = {"currency": pl.String, "rows": pl.UInt32, amount: pl.Float64}
    return pl.DataFrame(schema=schema)


def _convert_flows(
    rows: pl.DataFrame, settings: PremiumSettings, market: MarketData | None, cut_off: date
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int], list[Finding]]:
    """Amounts in the reporting currency (and restated): the rows, the rows not converted per
    currency, the number of rows per fallback flag and the findings of CV01 and CV02."""
    target = settings.reporting_currency
    adjusted = settings.value_basis is ValueBasis.INFLATION_ADJUSTED
    if target is None:
        if adjusted:
            raise PremiumError(
                "the inflation-adjusted basis needs a reporting currency: the index belongs "
                "to it (CV02)"
            )
        return rows, _nothing_left(), {}, []
    done = convert(
        rows,
        ["amount"],
        day="booking_date",
        rule=Rule.FLOW,
        target=target,
        market=market,
        max_lookback_days=MAX_LOOKBACK_DAYS,
    )
    flags = {str(k): int(v) for k, v in done.flagged().select("rate_flag", "rows").iter_rows()}
    findings: list[Finding] = []
    unconverted = finding(
        "premiums",
        "CV01",
        "WARNING",
        f"no exchange rate into {target}: premium left out, shown in original currency",
        done.frame.filter(pl.col("rate").is_null()).sort(SOURCE_ROW),
    )
    if unconverted:
        findings.append(unconverted)
    kept = done.frame.filter(pl.col("rate").is_not_null()).with_columns(
        pl.lit(target).alias("currency")
    )
    if adjusted:
        if market is None:
            raise PremiumError("the inflation-adjusted basis needs market data (CV02)")
        try:
            factors = restatement_factors(
                market,
                settings.price_index,
                settings.value_date or cut_off,
                kept.select(month_of("booking_date").alias("month")).to_series(),
            )
        except ConversionError as error:
            raise PremiumError(str(error)) from error
        kept = kept.with_columns(month_of("booking_date").alias("month")).join(
            factors.select("month", "factor"), on="month", how="left"
        )
        unrestated = finding(
            "premiums",
            "CV02",
            "WARNING",
            f"no value of {settings.price_index} for the booking month or any earlier one: "
            "premium not restated and left out",
            kept.filter(pl.col("factor").is_null()).sort(SOURCE_ROW),
        )
        if unrestated:
            findings.append(unrestated)
        kept = kept.filter(pl.col("factor").is_not_null()).with_columns(
            (pl.col("amount") * pl.col("factor")).alias("amount")
        )
    return kept, done.not_converted, flags, findings


def _joined(
    premiums: pl.DataFrame,
    policies: pl.DataFrame,
    settings: PremiumSettings,
    market: MarketData | None,
    cut_off: date,
    by: Sequence[str] = GROUP_BY,
    row_column: str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int], list[Finding]]:
    """Transactions known at `cut_off` on the basis of `settings`, joined to their policy.

    `by` are policy attributes carried along; `row_column`, when given, names a column of both
    frames that identifies the source row (lineage); the policy's one is `policy_row`.
    """
    if SOURCE_ROW not in premiums.columns:
        premiums = premiums.with_row_index(SOURCE_ROW, offset=2).cast({SOURCE_ROW: pl.Int64})
    rows = _transactions(premiums.filter(pl.col("booking_date") <= cut_off), settings)
    rows, not_converted, flags, findings = _convert_flows(rows, settings, market, cut_off)
    attributes = ["policy_id", "start_date", "end_date", *by]
    present = [a for a in attributes if a in policies.columns]
    absent = [pl.lit(None, pl.String).alias(a) for a in attributes if a not in policies.columns]
    marked = policies.select(
        *present,
        *absent,
        *([pl.col(row_column).alias("policy_row")] if row_column else []),
        pl.lit(True).alias("_linked"),
    )
    linked = rows.join(marked, on="policy_id", how="left")
    for left_out, rule, text in (
        (
            linked.filter(pl.col("_linked").is_null()),
            "DV-PRM-06",
            "policy not in policies: premium not earned",
        ),
        (
            linked.filter(pl.col("_linked").is_not_null() & pl.col("end_date").is_null()),
            "DV-POL-03",
            "policy without cover dates: premium not earned",
        ),
    ):
        found = finding("premiums", rule, "WARNING", text, left_out.sort(SOURCE_ROW))
        if found:
            findings.append(found)
    return linked.drop("_linked"), not_converted, flags, findings


def booked_transactions(
    premiums: pl.DataFrame, settings: PremiumSettings, market: MarketData | None, cut_off: date
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int], list[Finding]]:
    """Premium transactions booked up to `cut_off` on the basis of `settings`, converted and
    restated as flows (CV01, CV02, CV03): the rows with signed amounts, the original-currency
    totals of the rows without a rate, the fallback flags and the findings (PR01)."""
    if SOURCE_ROW not in premiums.columns:
        premiums = premiums.with_row_index(SOURCE_ROW, offset=2).cast({SOURCE_ROW: pl.Int64})
    rows = _transactions(premiums.filter(pl.col("booking_date") <= cut_off), settings)
    return _convert_flows(rows, settings, market, cut_off)


def _cut_off(premiums: pl.DataFrame, settings: PremiumSettings) -> date:
    """The cut-off month end: the setting, else the latest booking date (CV04)."""
    if premiums.height == 0:
        raise PremiumError("no premium transactions")
    cut = settings.cut_off or premiums["booking_date"].max()
    if not isinstance(cut, date):
        raise PremiumError("premiums has no usable booking dates")
    return month_end(month_index(cut))


def _intervals(
    linked: pl.DataFrame, by: Sequence[str] = GROUP_BY, row_column: str | None = None
) -> pl.DataFrame:
    """Earning interval [begin, end) of each transaction that has cover dates (PR02)."""
    return linked.filter(
        pl.col("start_date").is_not_null() & pl.col("end_date").is_not_null()
    ).select(
        *[pl.col(a).fill_null(UNKNOWN) for a in by],
        "currency",
        "amount",
        pl.max_horizontal("effective_date", "start_date").alias("begin"),
        pl.col("end_date").alias("end"),
        *([pl.col(row_column).alias("row"), pl.col("policy_row")] if row_column else []),
    )


def _lineage(row_column: str | None) -> list[pl.Expr]:
    """Aggregations that keep the source rows of the transactions and policies behind a value."""
    if row_column is None:
        return []
    return [
        pl.col("row").unique().sort().alias("rows"),
        pl.col("policy_row").unique().sort().alias("policy_rows"),
    ]


def earned_premium(
    premiums: pl.DataFrame,
    policies: pl.DataFrame,
    settings: PremiumSettings,
    market: MarketData | None = None,
    by: Sequence[str] = GROUP_BY,
    row_column: str | None = None,
) -> PremiumStructure:
    """Earned premium by the policy attributes `by` (default segment and line), currency and
    period up to the cut-off (PR02); with `row_column` also the source rows behind each value."""
    cut_off = _cut_off(premiums, settings)
    linked, not_converted, flags, findings = _joined(
        premiums, policies, settings, market, cut_off, by, row_column
    )
    expanded = _expand(_intervals(linked, by, row_column), settings, cut_off)
    grouped = (
        expanded.with_columns((pl.col("amount") * pl.col("share")).alias("earned_premium"))
        .group_by(*by, "currency", "period_number", maintain_order=True)
        .agg(pl.col("earned_premium").sum(), *_lineage(row_column))
    )
    frame = _label(grouped, settings).sort(*by, "currency", "period_number")
    return PremiumStructure(frame, not_converted, tuple(findings), cut_off, flags)


def unearned_premium(
    premiums: pl.DataFrame,
    policies: pl.DataFrame,
    settings: PremiumSettings,
    at: date,
    market: MarketData | None = None,
    by: Sequence[str] = GROUP_BY,
    row_column: str | None = None,
) -> PremiumStructure:
    """Premium booked on or before `at` that pays for cover after it (PR03).

    The nominal basis only; a stock, so it is converted at the period-end rate of `at`.
    """
    if settings.value_basis is not ValueBasis.NOMINAL:
        raise PremiumError("unearned premium exists on the nominal value basis only (PR03)")
    at_settings = settings.model_copy(update={"reporting_currency": None})
    linked, _, _, findings = _joined(premiums, policies, at_settings, None, at, by, row_column)
    total = (pl.col("end") - pl.col("begin")).dt.total_days()
    after = (
        pl.col("end") - pl.max_horizontal("begin", pl.lit(at) + pl.duration(days=1))
    ).dt.total_days()
    share = (
        pl.when(total <= 0)
        .then(pl.when(pl.col("begin") > at).then(1.0).otherwise(0.0))
        .otherwise(after.clip(lower_bound=0) / total)
    )
    grouped = (
        _intervals(linked, by, row_column)
        .with_columns((pl.col("amount") * share).alias("unearned_premium"))
        .group_by(*by, "currency", maintain_order=True)
        .agg(pl.col("unearned_premium").sum(), *_lineage(row_column))
        .sort(*by, "currency")
    )
    flags: dict[str, int] = {}
    not_converted = _nothing_left("unearned_premium")
    if settings.reporting_currency is not None:
        done = convert(
            grouped.with_columns(pl.lit(at).alias("valuation_date")),
            ["unearned_premium"],
            day="valuation_date",
            rule=Rule.STOCK,
            target=settings.reporting_currency,
            market=market,
        )
        flags = {str(k): int(v) for k, v in done.flagged().select("rate_flag", "rows").iter_rows()}
        not_converted = done.not_converted
        merged = (
            [
                pl.col("rows").list.explode().unique().sort(),
                pl.col("policy_rows").list.explode().unique().sort(),
            ]
            if row_column
            else []
        )
        grouped = (
            done.frame.filter(pl.col("rate").is_not_null())
            .with_columns(pl.lit(settings.reporting_currency).alias("currency"))
            .group_by(*by, "currency", maintain_order=True)
            .agg(pl.col("unearned_premium").sum(), *merged)
            .sort(*by, "currency")
        )
    return PremiumStructure(grouped, not_converted, tuple(findings), at, flags)


def earned_exposure(
    policies: pl.DataFrame,
    settings: PremiumSettings,
    cut_off: date,
    by: Sequence[str] = GROUP_BY,
    row_column: str | None = None,
    by_currency: bool = False,
) -> pl.DataFrame:
    """Earned exposure by the policy attributes `by`, period and optionally policy currency up
    to the cut-off (CV04).

    Cover runs from start_date to the earlier of end_date and cancellation_date; empty
    exposure_units count as 1. A policy with no cover dates or with start on or after end has
    no exposure (DV-POL-03, DV-POL-04). With `row_column` the policy rows behind each value
    are returned as `policy_rows`.
    """
    cut_off = month_end(month_index(cut_off))
    units = (
        pl.col("exposure_units").fill_null(1.0)
        if "exposure_units" in policies.columns
        else pl.lit(1.0)
    )
    cancel = (
        pl.col("cancellation_date")
        if "cancellation_date" in policies.columns
        else pl.lit(None, pl.Date)
    )
    keys = [
        pl.col(a).fill_null(UNKNOWN) if a in policies.columns else pl.lit(UNKNOWN).alias(a)
        for a in by
    ]
    currency = pl.col("currency") if by_currency else pl.lit("").alias("currency")
    intervals = policies.filter(
        pl.col("start_date").is_not_null() & pl.col("end_date").is_not_null()
    ).select(
        *keys,
        currency,
        units.alias("amount"),
        pl.col("start_date").alias("begin"),
        pl.min_horizontal(pl.col("end_date"), cancel.fill_null(pl.col("end_date"))).alias("end"),
        *([pl.col(row_column).alias("policy_row")] if row_column else []),
    )
    expanded = _expand(intervals.filter(pl.col("end") > pl.col("begin")), settings, cut_off)
    total = (pl.col("end") - pl.col("begin")).dt.total_days()
    days = pl.col("share") * total  # days of cover in the period
    lineage = [pl.col("policy_row").unique().sort().alias("policy_rows")] if row_column else []
    group_keys = [*by, "currency"] if by_currency else list(by)
    grouped = (
        expanded.with_columns((pl.col("amount") * days / DAYS_PER_YEAR).alias("earned_exposure"))
        .group_by(*group_keys, "period_number", maintain_order=True)
        .agg(pl.col("earned_exposure").sum(), *lineage)
    )
    return _label(grouped, settings).sort(*group_keys, "period_number")
