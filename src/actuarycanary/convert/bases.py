"""Amounts of claim valuations on the requested reinsurance, currency and value bases.

CV03: gross, ceded and net come from the valuation fields and net is gross minus ceded per
claim and valuation. CV01 and CV02: nominal amounts are converted with one constant rate
per currency (development analysis); inflation-adjusted amounts are converted at the rate
of their own date and then restated to the prices of the value date. The valuations hold
cumulative amounts, so the flows of the adjusted basis are rebuilt from consecutive rows
(CV04) and accumulated again after restating.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import polars as pl

from actuarycanary.canonical.feeds import Finding, finding
from actuarycanary.convert.currency import MAX_LOOKBACK_DAYS, Rule, lookup_rates
from actuarycanary.convert.inflation import restatement_factors
from actuarycanary.convert.market import ConversionError, MarketData, month_of
from actuarycanary.convert.rates import DevelopmentRates
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import month_index

PAID = "paid_to_date"
RESERVE = "case_reserve"
CEDED_PAID = "ceded_paid_to_date"
CEDED_RESERVE = "ceded_reserve"
SUBROGATION = "subrogation_to_date"
SALVAGE = "salvage_to_date"
FLOW_COMPONENTS = (PAID, CEDED_PAID, SUBROGATION, SALVAGE)  # cumulative flows
STOCK_COMPONENTS = (RESERVE, CEDED_RESERVE)  # amounts at the valuation date
CEDED_COMPONENTS = (CEDED_PAID, CEDED_RESERVE)

MONEY_MEASURES = (
    "paid",
    "incurred",
    "case_reserve",
    "subrogation",
    "salvage",
    "recoveries",
    "paid_net_of_recoveries",
)
COUNT_MEASURES = ("reported_count", "open_count", "closed_count")
MEASURES = (*MONEY_MEASURES, *COUNT_MEASURES)
CLOSED_STATUSES = ("CLOSED", "CLOSED_NIL")  # CL04
OPEN_STATUSES = ("OPEN", "REOPENED", "LITIGATED")

RESTATED = "r_"  # prefix of the restated component columns


class ReinsuranceBasis(StrEnum):
    GROSS = "GROSS"
    CEDED = "CEDED"
    NET = "NET"


class ValueBasis(StrEnum):
    NOMINAL = "NOMINAL"
    INFLATION_ADJUSTED = "INFLATION_ADJUSTED"


class BasisUnavailableError(ConversionError):
    """A measure cannot be given on the requested basis with the fields loaded (CV03)."""


@dataclass(frozen=True)
class RowBasis:
    """What the rows are converted and restated to."""

    reporting_currency: str
    value: ValueBasis
    development: DevelopmentRates  # constant rates, used on the nominal basis
    market: MarketData | None = None
    price_index: str | None = None
    value_date: date | None = None
    max_lookback_days: int = MAX_LOOKBACK_DAYS


@dataclass(frozen=True)
class MeasureColumns:
    """How one triangle measure is read from rows that carry the restated components."""

    value: pl.Expr  # amount in reporting currency on the basis
    present: pl.Expr  # False for rows left out of the measure (an empty amount, DV-CLV-02)
    usable: pl.Expr  # False for rows that could not be converted or restated
    money: bool


def components(measure: str, reinsurance: ReinsuranceBasis) -> list[tuple[int, str]]:
    """Signed fields whose sum is `measure` on the reinsurance basis (CV03)."""
    paid = {
        ReinsuranceBasis.GROSS: [(1, PAID)],
        ReinsuranceBasis.CEDED: [(1, CEDED_PAID)],
        ReinsuranceBasis.NET: [(1, PAID), (-1, CEDED_PAID)],
    }[reinsurance]
    reserve = {
        ReinsuranceBasis.GROSS: [(1, RESERVE)],
        ReinsuranceBasis.CEDED: [(1, CEDED_RESERVE)],
        ReinsuranceBasis.NET: [(1, RESERVE), (-1, CEDED_RESERVE)],
    }[reinsurance]
    match measure:
        case "paid":
            return paid
        case "case_reserve":
            return reserve
        case "incurred":
            return paid + reserve
        case "paid_net_of_recoveries":  # CV03: P - subrogation - salvage, gross only
            if reinsurance is not ReinsuranceBasis.GROSS:
                raise BasisUnavailableError(
                    "paid net of recoveries is not part of the reinsurance basis, "
                    "only GROSS exists (CV03)"
                )
            return [(1, PAID), (-1, SUBROGATION), (-1, SALVAGE)]
        case "subrogation" | "salvage" | "recoveries":
            if reinsurance is not ReinsuranceBasis.GROSS:
                raise BasisUnavailableError(
                    f"{measure} is not part of the reinsurance basis, only GROSS exists (CV03)"
                )
            fields = {
                "subrogation": [SUBROGATION],
                "salvage": [SALVAGE],
                "recoveries": [SUBROGATION, SALVAGE],
            }[measure]
            return [(1, f) for f in fields]
    raise ValueError(f"unknown money measure {measure}")


def required_columns(
    measures: Collection[str], reinsurance: ReinsuranceBasis, present: Collection[str]
) -> list[str]:
    """Fields the measures read; raises BasisUnavailableError when one is not loaded (CV03)."""
    needed: list[str] = []
    for measure in measures:
        if measure in COUNT_MEASURES:
            continue
        for _, name in components(measure, reinsurance):
            if name not in present:
                raise BasisUnavailableError(
                    f"{measure} on the {reinsurance.value} basis needs {name}, which the "
                    "claim valuations do not have; the basis is not set equal to gross (CV03)"
                )
            if name not in needed:
                needed.append(name)
    return needed


def measure_columns(measure: str, reinsurance: ReinsuranceBasis) -> MeasureColumns:
    """Expressions over rows from `restate_rows` (money) or over status (counts)."""
    if measure in COUNT_MEASURES:
        status = pl.col("status")
        indicator = {
            "reported_count": pl.lit(True),
            "open_count": status.is_in(OPEN_STATUSES),
            "closed_count": status.is_in(CLOSED_STATUSES),
        }[measure]
        return MeasureColumns(indicator.cast(pl.Float64), pl.lit(True), pl.lit(True), False)
    terms = components(measure, reinsurance)
    value = pl.sum_horizontal(sign * pl.col(RESTATED + name) for sign, name in terms)
    present = pl.all_horizontal(pl.col(name).is_not_null() for _, name in terms)
    names = [name for _, name in terms]
    usable = pl.lit(True)
    if any(n in FLOW_COMPONENTS for n in names):
        usable = usable & pl.col("ok_flow")
    if any(n in STOCK_COMPONENTS for n in names):
        usable = usable & pl.col("ok_stock")
    return MeasureColumns(value, present, usable, True)


def _note(
    rows: pl.DataFrame, condition: pl.Expr, rule: str, severity: str, message: str
) -> Finding | None:
    return finding("claim_valuations", rule, severity, message, rows.filter(condition))


def _value_date_note(basis: RowBasis) -> Finding | None:
    """CV02: a value date whose month has no index value takes the latest earlier month."""
    assert basis.market is not None and basis.value_date is not None
    table = basis.market.index(basis.price_index or "")
    if table is None or (table["key"] == month_index(basis.value_date)).any():
        return None
    return Finding(
        "market",
        "CV02",
        "INFO",
        1,
        f"{basis.price_index} has no value for the month of the value date {basis.value_date}: "
        "the latest earlier month is used",
    )


def restate_rows(
    rows: pl.DataFrame, names: Collection[str], basis: RowBasis
) -> tuple[pl.DataFrame, list[Finding]]:
    """Add the restated component columns `r_<field>`, `ok_flow` and `ok_stock` to `rows`.

    `rows` hold claim_id, valuation_date, currency, SOURCE_ROW and the fields `names`
    (cumulative amounts in original currency, ceded fields already without empty cells).
    Rows are returned sorted by claim, valuation date and source row.
    """
    rows = rows.sort("claim_id", "valuation_date", SOURCE_ROW)
    flow_names = [n for n in names if n in FLOW_COMPONENTS]
    stock_names = [n for n in names if n in STOCK_COMPONENTS]
    if basis.value is ValueBasis.NOMINAL:
        rate = pl.col("currency").replace_strict(
            dict(basis.development.rates), default=None, return_dtype=pl.Float64
        )
        restated = rows.with_columns(
            *[(pl.col(n) * rate).alias(RESTATED + n) for n in names],
            rate.is_not_null().alias("ok_flow"),
            rate.is_not_null().alias("ok_stock"),
        )
        return restated, []

    if basis.market is None or basis.price_index is None or basis.value_date is None:
        raise ConversionError("the inflation-adjusted basis needs market data (CV02)")
    keys = rows.select("currency", pl.col("valuation_date").alias("day"))
    flow_rates = lookup_rates(
        basis.market, basis.reporting_currency, keys, Rule.DERIVED_FLOW, basis.max_lookback_days
    ).select(
        "currency", "day", pl.col("rate").alias("flow_rate"), pl.col("flag").alias("flow_flag")
    )
    stock_rates = lookup_rates(
        basis.market, basis.reporting_currency, keys, Rule.STOCK, basis.max_lookback_days
    ).select(
        "currency",
        "day",
        pl.col("rate").alias("stock_rate"),
        pl.col("flag").alias("stock_flag"),
    )
    factors = restatement_factors(
        basis.market,
        basis.price_index,
        basis.value_date,
        rows.select(month_of("valuation_date").alias("month")).to_series(),
    )
    on = ["currency", "day"]
    data = (
        rows.with_columns(
            pl.col("valuation_date").alias("day"), month_of("valuation_date").alias("month")
        )
        .join(flow_rates, on=on, how="left")
        .join(stock_rates, on=on, how="left")
        .join(factors.rename({"flag": "index_flag"}), on="month", how="left")
        .sort("claim_id", "valuation_date", SOURCE_ROW)
    )
    flow_ok = pl.col("flow_rate").is_not_null() & pl.col("factor").is_not_null()
    data = data.with_columns(
        flow_ok.cast(pl.Int8).cum_min().over("claim_id").cast(pl.Boolean).alias("ok_flow"),
        (pl.col("stock_rate").is_not_null() & pl.col("factor").is_not_null()).alias("ok_stock"),
        *[pl.col(n).forward_fill().over("claim_id").alias("_ff_" + n) for n in flow_names],
    )
    data = data.with_columns(
        *[
            (pl.col("_ff_" + n) - pl.col("_ff_" + n).shift(1).over("claim_id").fill_null(0.0))
            .fill_null(0.0)
            .alias("_flow_" + n)
            for n in flow_names
        ]
    )
    data = data.with_columns(
        *[
            pl.when(flow_ok)
            .then(pl.col("_flow_" + n) * pl.col("flow_rate") * pl.col("factor"))
            .otherwise(0.0)
            .cum_sum()
            .over("claim_id")
            .alias(RESTATED + n)
            for n in flow_names
        ],
        *[
            (pl.col(n) * pl.col("stock_rate") * pl.col("factor")).alias(RESTATED + n)
            for n in stock_names
        ],
    )
    notes = [
        _value_date_note(basis),
        _note(
            data,
            pl.col("flow_rate").is_null(),
            "CV01",
            "WARNING",
            "no FX_PERIOD_AVERAGE or FX_PERIOD_END rate for the booking month: flows not "
            "converted, claim left out of the inflation-adjusted triangles from this row on",
        ),
        _note(
            data,
            pl.col("flow_flag") != "",
            "CV01",
            "INFO",
            "FX_PERIOD_END rate used because the FX_PERIOD_AVERAGE rate of the booking month "
            "is missing",
        ),
        _note(
            data,
            pl.col("stock_rate").is_null(),
            "CV01",
            "WARNING",
            "no period-end or spot rate for the valuation date: reserves not converted",
        ),
        _note(
            data,
            pl.col("stock_flag") != "",
            "CV01",
            "INFO",
            "FX_SPOT rate used because the FX_PERIOD_END rate of the month is missing",
        ),
        _note(
            data,
            pl.col("factor").is_null(),
            "CV02",
            "WARNING",
            f"no value of {basis.price_index} for the month or any earlier one: not restated",
        ),
        _note(
            data,
            pl.col("index_flag") != "",
            "CV02",
            "INFO",
            f"{basis.price_index} of the latest earlier month used for a missing month",
        ),
    ]
    added = [RESTATED + n for n in (*flow_names, *stock_names)]
    return data.select(*rows.columns, *added, "ok_flow", "ok_stock"), [
        n for n in notes if n is not None
    ]
