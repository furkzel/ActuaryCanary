"""Robust z-score anomaly flags (MT08) on payments and case-reserve movements.

Flows follow CV04: consecutive rows of a claim, in date order, differenced; the first row's
flow is its full value. Amounts are converted with the constant development rate of the
row's currency (CV01); a value whose currency has no rate is not scored and is counted.

A case-reserve movement is judged against movements of its own kind in its segment and line
(MT08 1.2.0, record 0221): a reserve that moved while positive on both sides, a reserve
opened from nothing and a reserve released to nothing. A reserve that did not move is not a
movement. Mixing the kinds put the openings and releases, which are status changes, far from
the typical small movement and flagged 40 to 45 % of MOTOR_OD.

The incurred change at a payment is the movement of paid plus case reserve on a row with a
payment, when the reserve did not absorb it: a payment the case reserve did not foresee
(MT08 1.1.0, record 0060).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from actuarycanary.io.excel import SOURCE_ROW

THRESHOLD = 3.5  # Iglewicz and Hoaglin (1993)
MIN_GROUP_SIZE = 30
MAX_FLAG_RATE = 0.05  # above it the group may mix populations (MT08)
MAD_SCALE = 0.6745
MEAN_AD_SCALE = 1.253314
GROUP_BY = ("segment", "line")
RESERVE_VARIABLES = ("reserve_change", "reserve_opening", "reserve_release")
VARIABLES = ("paid_flow", *RESERVE_VARIABLES, "incurred_change_at_payment")
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RobustZ:
    scores: pl.DataFrame  # every scored value with its z
    flags: pl.DataFrame  # flagged values with their reason
    flag_rates: pl.DataFrame  # per group and variable: values, flagged, rate, status
    not_converted: int  # values left out because their currency has no rate
    warnings: tuple[str, ...]
    threshold: float


def _rows(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    rates: Mapping[str, float],
    group_by: Sequence[str],
) -> pl.DataFrame:
    rows = valuations
    if claims is not None:
        present = [g for g in group_by if g in claims.columns]
        rows = rows.join(claims.select("claim_id", *present), on="claim_id", how="left")
    rows = rows.with_columns(
        [
            pl.col(g).fill_null(UNKNOWN) if g in rows.columns else pl.lit(UNKNOWN).alias(g)
            for g in group_by
        ]
    )
    rate = pl.col("currency").replace_strict(dict(rates), default=None, return_dtype=pl.Float64)
    order = (
        ["claim_id", "valuation_date", SOURCE_ROW]
        if SOURCE_ROW in rows.columns
        else ["claim_id", "valuation_date"]
    )
    return rows.sort(order).with_columns(rate.alias("rate"))


def _paid_flows(rows: pl.DataFrame, group_by: Sequence[str]) -> pl.DataFrame:
    paid = rows.filter(pl.col("paid_to_date").is_not_null())
    flow = pl.col("paid_to_date") - pl.col("paid_to_date").shift(1).over("claim_id").fill_null(0.0)
    return (
        paid.with_columns(flow.alias("original"))
        .filter(pl.col("original") > 0)
        .with_columns(
            pl.lit("paid_flow").alias("variable"),
            (pl.col("original") * pl.col("rate")).alias("amount"),
            pl.lit(None, dtype=pl.Float64).alias("before"),
        )
        .with_columns(pl.col("amount").log().alias("y"))
        .select(_columns(rows, group_by))
    )


def _reserve_changes(rows: pl.DataFrame, group_by: Sequence[str]) -> pl.DataFrame:
    reserve = rows.filter(pl.col("case_reserve").is_not_null()).with_columns(
        (pl.col("case_reserve") * pl.col("rate")).alias("amount"),
        pl.col("case_reserve").shift(1).over("claim_id").alias("previous"),
        pl.col("rate").shift(1).over("claim_id").alias("previous_rate"),
    )
    kind = (
        pl.when(pl.col("previous") <= 0)
        .then(pl.lit("reserve_opening"))
        .when(pl.col("case_reserve") <= 0)
        .then(pl.lit("reserve_release"))
        .otherwise(pl.lit("reserve_change"))
    )
    return (
        reserve.filter(
            pl.col("previous").is_not_null()
            & (pl.col("case_reserve") != pl.col("previous"))
            & ((pl.col("case_reserve") > 0) | (pl.col("previous") > 0))
        )
        .with_columns(
            kind.alias("variable"),
            (pl.col("previous") * pl.col("previous_rate")).alias("before"),
            pl.when(pl.col("previous_rate").is_null())
            .then(None)
            .otherwise(pl.col("rate"))
            .alias("rate"),
        )
        .with_columns(((pl.col("amount") + 1) / (pl.col("before") + 1)).log().alias("y"))
        .select(_columns(rows, group_by))
    )


def _incurred_changes(rows: pl.DataFrame, group_by: Sequence[str]) -> pl.DataFrame:
    """ln((I+ + 1) / (I+ before + 1)) on rows with a positive paid flow whose incurred moved;
    rows with paid and reserve only, each converted at its own rate."""
    both = rows.filter(pl.col("paid_to_date").is_not_null() & pl.col("case_reserve").is_not_null())
    incurred = (pl.col("paid_to_date") + pl.col("case_reserve")).alias("incurred")
    previous = pl.col("incurred").shift(1).over("claim_id")
    flow = pl.col("paid_to_date") - pl.col("paid_to_date").shift(1).over("claim_id")
    return (
        both.with_columns(incurred)
        .with_columns(
            flow.alias("flow"),
            previous.alias("previous"),
            pl.col("rate").shift(1).over("claim_id").alias("previous_rate"),
        )
        .filter((pl.col("flow") > 0) & (pl.col("incurred") != pl.col("previous")))
        .with_columns(
            pl.lit("incurred_change_at_payment").alias("variable"),
            (pl.col("previous") * pl.col("previous_rate")).clip(lower_bound=0).alias("before"),
            (pl.col("incurred") * pl.col("rate")).clip(lower_bound=0).alias("amount"),
            pl.when(pl.col("previous_rate").is_null())
            .then(None)
            .otherwise(pl.col("rate"))
            .alias("rate"),
        )
        .with_columns(((pl.col("amount") + 1) / (pl.col("before") + 1)).log().alias("y"))
        .select(_columns(rows, group_by))
    )


def _columns(rows: pl.DataFrame, group_by: Sequence[str]) -> list[str]:
    source = [SOURCE_ROW] if SOURCE_ROW in rows.columns else []
    return [
        "claim_id",
        "valuation_date",
        *source,
        "currency",
        *group_by,
        "variable",
        "before",
        "amount",
        "rate",
        "y",
    ]


def _reason() -> pl.Expr:
    z = pl.col("z").abs().round(2).cast(pl.String)
    paid = pl.format(
        "payment of {} is {} times the median payment {} of its group (robust z {}, threshold {})",
        pl.col("amount").round(2),
        (pl.col("y") - pl.col("median")).exp().round(1),
        pl.col("median").exp().round(2),
        z,
        pl.col("threshold"),
    )
    reserve = pl.format(
        "case reserve moved from {} to {}, log change {} against the group median {} "
        "(robust z {}, threshold {})",
        pl.col("before").round(2),
        pl.col("amount").round(2),
        pl.col("y").round(3),
        pl.col("median").round(3),
        z,
        pl.col("threshold"),
    )
    opening = pl.format(
        "case reserve opened at {}, log size {} against the group median {} of reserves "
        "opened (robust z {}, threshold {})",
        pl.col("amount").round(2),
        pl.col("y").round(3),
        pl.col("median").round(3),
        z,
        pl.col("threshold"),
    )
    release = pl.format(
        "case reserve of {} released, log change {} against the group median {} of reserves "
        "released (robust z {}, threshold {})",
        pl.col("before").round(2),
        pl.col("y").round(3),
        pl.col("median").round(3),
        z,
        pl.col("threshold"),
    )
    incurred = pl.format(
        "incurred moved from {} to {} with a payment, log change {} against the group median {} "
        "(robust z {}, threshold {})",
        pl.col("before").round(2),
        pl.col("amount").round(2),
        pl.col("y").round(3),
        pl.col("median").round(3),
        z,
        pl.col("threshold"),
    )
    return (
        pl.when(pl.col("variable") == "paid_flow")
        .then(paid)
        .when(pl.col("variable") == "reserve_change")
        .then(reserve)
        .when(pl.col("variable") == "reserve_opening")
        .then(opening)
        .when(pl.col("variable") == "reserve_release")
        .then(release)
        .otherwise(incurred)
    )


def robust_z_flags(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    rates: Mapping[str, float],
    *,
    threshold: float = THRESHOLD,
    min_group_size: int = MIN_GROUP_SIZE,
    group_by: Sequence[str] = GROUP_BY,
    variables: Sequence[str] = VARIABLES,
) -> RobustZ:
    """MT08 on canonical claim valuations; `claims` supplies the groups (UNKNOWN when absent).
    `rates` is the constant development rate per currency into the reporting currency."""
    unknown = [v for v in variables if v not in VARIABLES]
    if unknown:
        raise ValueError(
            f"unknown variables: {', '.join(unknown)}; allowed: {', '.join(VARIABLES)}"
        )
    group_by = list(group_by)
    rows = _rows(valuations, claims, rates, group_by)
    parts = {
        "paid_flow": (_paid_flows, ("paid_flow",)),
        "reserve": (_reserve_changes, RESERVE_VARIABLES),
        "incurred_change_at_payment": (_incurred_changes, ("incurred_change_at_payment",)),
    }
    values = pl.concat(
        [
            build(rows, group_by).filter(pl.col("variable").is_in(list(variables)))
            for build, produces in parts.values()
            if set(produces) & set(variables)
        ]
    )
    not_converted = values.filter(pl.col("rate").is_null()).height
    values = values.filter(pl.col("rate").is_not_null())

    keys = [*group_by, "variable"]
    stats = values.group_by(keys).agg(
        pl.len().alias("values"), pl.col("y").median().alias("median")
    )
    values = values.join(stats, on=keys).with_columns((pl.col("y") - pl.col("median")).alias("d"))
    spread = values.group_by(keys).agg(
        pl.col("d").abs().median().alias("mad"), pl.col("d").abs().mean().alias("mean_ad")
    )
    scored = (
        values.join(spread, on=keys)
        .filter(pl.col("values") >= min_group_size)
        .with_columns(
            pl.when(pl.col("mad") > 0)
            .then(MAD_SCALE * pl.col("d") / pl.col("mad"))
            .when(pl.col("mean_ad") > 0)
            .then(pl.col("d") / (MEAN_AD_SCALE * pl.col("mean_ad")))
            .otherwise(0.0)
            .alias("z"),
            pl.lit(threshold).alias("threshold"),
        )
        .with_columns((pl.col("z").abs() > threshold).alias("flagged"))
    )
    flags = scored.filter(pl.col("flagged")).with_columns(_reason().alias("reason"))
    rates_frame = (
        stats.join(
            scored.group_by(keys).agg(pl.col("flagged").sum().alias("flagged")), on=keys, how="left"
        )
        .with_columns(
            pl.when(pl.col("values") >= min_group_size)
            .then(pl.lit("scored"))
            .otherwise(pl.lit("too few values"))
            .alias("status"),
            pl.col("flagged").fill_null(0),
        )
        .with_columns(
            pl.when(pl.col("status") == "scored")
            .then(pl.col("flagged") / pl.col("values"))
            .otherwise(None)
            .alias("rate")
        )
        .drop("median")
        .sort(keys)
    )
    warnings = tuple(
        f"{'/'.join(str(g) for g in r[:-2])} {r[-2]}: {r[-1]:.1%} of values flagged, above "
        f"{MAX_FLAG_RATE:.0%}; the group may mix populations (for example two currencies)"
        for r in rates_frame.filter(pl.col("rate") > MAX_FLAG_RATE)
        .select(*keys, "rate")
        .iter_rows()
    )
    order = ["claim_id", "valuation_date", "variable"]
    return RobustZ(
        scores=scored.drop("d", "mad", "mean_ad").sort(order),
        flags=flags.drop("d", "mad", "mean_ad", "flagged").sort(order),
        flag_rates=rates_frame,
        not_converted=not_converted,
        warnings=warnings,
        threshold=threshold,
    )
