"""Isolation forest anomaly flags (MT09) on claim-level features at the cut-off.

Each group (segment by default) gets its own forest; claims are sorted by claim_id before
fitting, so scores depend on the data and the seed only, never on row order. Every tree sees
every claim of its group by default: in a sample of 256 out of thousands of claims, a feature
that is non-zero for a handful of claims (negative paid flows) is constant in most trees and
never split on (MT09 1.1.0, record 0061).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import polars as pl
from sklearn.ensemble import IsolationForest

from actuarycanary.io.excel import SOURCE_ROW

N_ESTIMATORS = 200
MAX_SAMPLES: int | Literal["all"] = "all"  # every claim of the group; an integer caps it
CONTAMINATION = 0.01
SEED = 1
MIN_GROUP_SIZE = 100
GROUP_BY = ("segment",)
UNKNOWN = "UNKNOWN"
OPEN_STATUSES = ("OPEN", "REOPENED", "LITIGATED")  # CL04
PAID_SHARE_CAP = 2.0
FEATURES = (
    "log_incurred",
    "log_paid",
    "paid_share",
    "months_since_first_valuation",
    "reserve_change_share",
    "log_largest_payment",
    "largest_log_reserve_change",
    "negative_payments",
    "open",
    "reporting_delay_days",
)


@dataclass(frozen=True)
class IsolationFlags:
    scores: pl.DataFrame  # claim_id, group, features, score, rank, flagged
    flags: pl.DataFrame  # flagged claims with score, rank, features and reason
    groups: pl.DataFrame  # per group: claims, flagged, status
    features: tuple[str, ...]
    seed: int


def claim_features(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    rates: Mapping[str, float],
    cut_off: date,
    group_by: Sequence[str] = GROUP_BY,
) -> pl.DataFrame:
    """One row per claim with the MT09 features, in the reporting currency (constant rate).

    Amounts of a row whose currency has no rate count as zero; the reporting delay is left
    out when claims is not loaded or has no report and occurrence dates."""
    order = (
        ["claim_id", "valuation_date", SOURCE_ROW]
        if SOURCE_ROW in valuations.columns
        else ["claim_id", "valuation_date"]
    )
    rows = (
        valuations.filter(pl.col("valuation_date") <= cut_off)
        .sort(order)
        .with_columns(
            pl.col("currency")
            .replace_strict(dict(rates), default=0.0, return_dtype=pl.Float64)
            .alias("rate")
        )
        .with_columns(
            (
                pl.col("paid_to_date").fill_null(strategy="forward").over("claim_id").fill_null(0.0)
                * pl.col("rate")
            ).alias("paid"),
            (
                pl.col("case_reserve").fill_null(strategy="forward").over("claim_id").fill_null(0.0)
                * pl.col("rate")
            ).alias("reserve"),
        )
        .with_columns(
            (pl.col("paid") - pl.col("paid").shift(1).over("claim_id").fill_null(0.0)).alias(
                "flow"
            ),
            pl.col("reserve").shift(1).over("claim_id").alias("previous_reserve"),
        )
        .with_columns(
            ((pl.col("reserve") + 1) / (pl.col("previous_reserve") + 1))
            .log()
            .abs()
            .alias("log_change")
        )
    )
    cut_month = cut_off.year * 12 + cut_off.month - 1
    first_month = (
        pl.col("valuation_date").min().dt.year() * 12
        + pl.col("valuation_date").min().dt.month()
        - 1
    )
    features = rows.group_by("claim_id").agg(
        pl.col("paid").last().alias("paid"),
        (pl.col("paid").last() + pl.col("reserve").last()).alias("incurred"),
        (pl.lit(cut_month) - first_month).cast(pl.Float64).alias("months_since_first_valuation"),
        (
            pl.col("previous_reserve").is_not_null()
            & (pl.col("reserve") != pl.col("previous_reserve"))
        )
        .sum()
        .alias("changes"),
        (pl.len() - 1).alias("pairs"),
        pl.col("flow").max().alias("largest_flow"),
        pl.col("log_change").max().fill_null(0.0).alias("largest_log_reserve_change"),
        (pl.col("flow") < 0).sum().cast(pl.Float64).alias("negative_payments"),
        pl.col("status").last().is_in(OPEN_STATUSES).cast(pl.Float64).alias("open"),
    )
    features = features.with_columns(
        (1 + pl.col("incurred").clip(lower_bound=0)).log().alias("log_incurred"),
        (1 + pl.col("paid").clip(lower_bound=0)).log().alias("log_paid"),
        pl.when(pl.col("incurred") == 0)
        .then(0.0)
        .otherwise(pl.col("paid") / pl.col("incurred"))
        .clip(0.0, PAID_SHARE_CAP)
        .alias("paid_share"),
        pl.when(pl.col("pairs") > 0)
        .then(pl.col("changes") / pl.col("pairs"))
        .otherwise(0.0)
        .alias("reserve_change_share"),
        (1 + pl.col("largest_flow").clip(lower_bound=0)).log().alias("log_largest_payment"),
    )
    header = ["claim_id"]
    if claims is not None:
        header += [g for g in group_by if g in claims.columns]
        dated = {"report_date", "occurrence_date"} <= set(claims.columns)
        delay = (
            [
                (pl.col("report_date") - pl.col("occurrence_date"))
                .dt.total_days()
                .cast(pl.Float64)
                .alias("reporting_delay_days")
            ]
            if dated
            else []
        )
        features = features.join(claims.select(*header, *delay), on="claim_id", how="left")
    features = features.with_columns(
        [
            pl.col(g).fill_null(UNKNOWN) if g in features.columns else pl.lit(UNKNOWN).alias(g)
            for g in group_by
        ]
    )
    present = [f for f in FEATURES if f in features.columns]
    return features.select("claim_id", *group_by, *present).sort("claim_id")


def isolation_forest_flags(
    features: pl.DataFrame,
    *,
    n_estimators: int = N_ESTIMATORS,
    max_samples: int | Literal["all"] = MAX_SAMPLES,
    contamination: float = CONTAMINATION,
    seed: int = SEED,
    min_group_size: int = MIN_GROUP_SIZE,
    group_by: Sequence[str] = GROUP_BY,
) -> IsolationFlags:
    """MT09 on `claim_features` output. Within each group the ceil(contamination x claims)
    highest scores are flagged; a claim with an empty feature (reporting delay without
    dates) takes the group median for it."""
    group_by = list(group_by)
    names = [f for f in FEATURES if f in features.columns]
    scored: list[pl.DataFrame] = []
    summary: list[dict[str, object]] = []
    features = features.sort("claim_id")
    for key, frame in features.group_by(group_by, maintain_order=True):
        values = frame.select(names).with_columns(
            [pl.col(n).fill_null(pl.col(n).median()).fill_null(0.0) for n in names]
        )
        row = dict(zip(group_by, key, strict=True))
        if frame.height < min_group_size:
            summary.append(
                {**row, "claims": frame.height, "flagged": 0, "status": "too few claims"}
            )
            continue
        size = frame.height if max_samples == "all" else min(max_samples, frame.height)
        forest = IsolationForest(
            n_estimators=n_estimators,
            max_samples=size,  # type: ignore[arg-type]
            contamination="auto",
            bootstrap=False,
            random_state=seed,
        ).fit(values.to_numpy())
        score = -forest.score_samples(values.to_numpy())  # s(x) of the original paper
        n_flag = math.ceil(contamination * frame.height)
        rank = np.empty(frame.height, dtype=np.int64)
        rank[np.argsort(-score, kind="stable")] = np.arange(1, frame.height + 1)
        scored.append(
            frame.with_columns(
                pl.Series("score", score),
                pl.Series("rank", rank),
                pl.Series("flagged", rank <= n_flag),
            )
        )
        summary.append({**row, "claims": frame.height, "flagged": n_flag, "status": "scored"})
    scores = (
        pl.concat(scored)
        if scored
        else features.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("score"),
            pl.lit(None, dtype=pl.Int64).alias("rank"),
            pl.lit(False).alias("flagged"),
        ).clear()
    )
    medians = scores.group_by(group_by).agg(
        [pl.col(n).median().alias(f"{n}_median") for n in names]
    )
    flags = scores.filter(pl.col("flagged")).join(medians, on=group_by, how="left")
    flags = flags.with_columns(_reason(names).alias("reason")).drop([f"{n}_median" for n in names])
    return IsolationFlags(
        scores=scores.sort("claim_id"),
        flags=flags.sort([*group_by, "rank"]),
        groups=pl.DataFrame(summary, schema_overrides={"flagged": pl.Int64}),
        features=tuple(names),
        seed=seed,
    )


def _reason(names: Sequence[str]) -> pl.Expr:
    """Score, rank and the three features furthest from the group median, as text."""
    parts = [
        pl.format(
            "{} {} (group median {})", pl.lit(n), pl.col(n).round(3), pl.col(f"{n}_median").round(3)
        )
        for n in names
    ]
    distance = [
        ((pl.col(n) - pl.col(f"{n}_median")).abs() / (pl.col(f"{n}_median").abs() + 1))
        for n in names
    ]
    ranked = pl.concat_list(distance).list.eval(pl.element().rank("ordinal", descending=True))
    chosen = [
        pl.when(ranked.list.get(i) <= 3).then(parts[i]).otherwise(None) for i in range(len(names))
    ]
    return pl.format(
        "isolation score {} (rank {} in its group); {}",
        pl.col("score").round(4),
        pl.col("rank"),
        pl.concat_str(chosen, separator="; ", ignore_nulls=True),
    )
