"""Anomalies and large losses (M06): the robust z-score (MT08) and the isolation forest (MT09)
on the canonical valuations, written as one table of flags (record 0057).

Each flag says which method raised it, on which claim and value, its score, the reason in
words and the spreadsheet rows behind it. The flags are leads for a reviewer, not findings of
error. After records 0060 and 0061 MT08 finds all injected payment faults of baseline and
high_inflation medium (8 of 8) and MT09 has an AUC of 0.90 and 0.89. Since MT08 1.2.0 (record
0221) case-reserve movements are scored by kind and no line has more than 2 % of them flagged.
"""

from dataclasses import dataclass
from datetime import date

import polars as pl

from actuarycanary.convert.rates import DevelopmentRates
from actuarycanary.io.excel import SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET
from actuarycanary.methods.isolation_forest import (
    IsolationFlags,
    claim_features,
    isolation_forest_flags,
)
from actuarycanary.methods.robust_z import RobustZ, robust_z_flags

ANOMALY_COLUMNS = (
    "method",
    "claim_id",
    "segment",
    "line",
    "valuation_date",
    "variable",
    "value",
    "score",
    "threshold",
    "reason",
    "file",
    "sheet",
    "rows",
)
ROBUST = "MT08"
ISOLATION = "MT09"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AnomalyResult:
    flags: pl.DataFrame
    robust: RobustZ
    isolation: IsolationFlags
    reasons: tuple[str, ...]  # what limited the methods, for the module outcome

    def counts(self) -> pl.DataFrame:
        """Flags per method, segment and line."""
        return (
            self.flags.group_by("method", "segment", "line")
            .agg(pl.len().alias("flags"))
            .sort("method", "segment", "line")
        )


def spans(rows: list[int]) -> str:
    """Sorted spreadsheet rows as "2-5;9"."""
    ordered = sorted(set(rows))
    parts: list[str] = []
    start = previous = None
    for row in ordered:
        if start is None:
            start = previous = row
        elif row == previous + 1:  # type: ignore[operator]
            previous = row
        else:
            parts.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = row
    if start is not None:
        parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ";".join(parts)


def _robust_rows(robust: RobustZ, valuations: pl.DataFrame) -> pl.DataFrame:
    where = valuations.select("claim_id", "valuation_date", SOURCE_ROW, SOURCE_FILE, SOURCE_SHEET)
    return (
        robust.flags.join(where, on=["claim_id", "valuation_date", SOURCE_ROW], how="left")
        .unique(subset=["claim_id", "valuation_date", "variable", SOURCE_ROW], keep="first")
        .select(
            pl.lit(ROBUST).alias("method"),
            "claim_id",
            "segment",
            "line",
            "valuation_date",
            "variable",
            pl.col("y").alias("value"),
            pl.col("z").alias("score"),
            "threshold",
            "reason",
            pl.col(SOURCE_FILE).alias("file"),
            pl.col(SOURCE_SHEET).alias("sheet"),
            pl.col(SOURCE_ROW).cast(pl.String).alias("rows"),
        )
    )


def _isolation_rows(
    isolation: IsolationFlags, valuations: pl.DataFrame, claims: pl.DataFrame | None
) -> pl.DataFrame:
    flagged = isolation.flags.select("claim_id", "segment", "score", "reason")
    lines = (
        claims.select("claim_id", "line").unique("claim_id")
        if claims is not None and "line" in claims.columns
        else pl.DataFrame(schema={"claim_id": pl.String, "line": pl.String})
    )
    flagged = flagged.join(lines, on="claim_id", how="left")
    behind = (
        valuations.filter(pl.col("claim_id").is_in(flagged["claim_id"].to_list()))
        .group_by("claim_id")
        .agg(
            pl.col(SOURCE_ROW).sort().alias("_rows"),
            pl.col(SOURCE_FILE).unique().sort().str.join(", ").alias("file"),
            pl.col(SOURCE_SHEET).unique().sort().str.join(", ").alias("sheet"),
        )
    )
    joined = flagged.join(behind, on="claim_id", how="left")
    return joined.select(
        pl.lit(ISOLATION).alias("method"),
        "claim_id",
        "segment",
        "line",
        pl.lit(None, pl.Date).alias("valuation_date"),
        pl.lit("claim").alias("variable"),
        pl.lit(None, pl.Float64).alias("value"),
        "score",
        pl.lit(None, pl.Float64).alias("threshold"),
        "reason",
        "file",
        "sheet",
        pl.col("_rows")
        .map_elements(lambda r: spans(list(r)), return_dtype=pl.String)
        .alias("rows"),
    )


def _groups(n: int) -> str:
    return f"{n} group has" if n == 1 else f"{n} groups have"


def run_anomalies(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    rates: DevelopmentRates,
    cut_off: date,
) -> AnomalyResult:
    """MT08 and MT09 on the canonical feeds with the constant development rates (CV01)."""
    robust = robust_z_flags(valuations, claims, rates.rates)
    features = claim_features(valuations, claims, rates.rates, cut_off)
    isolation = isolation_forest_flags(features)
    flags = pl.concat(
        [_robust_rows(robust, valuations), _isolation_rows(isolation, valuations, claims)],
        how="vertical_relaxed",
    ).sort("method", "segment", "line", "claim_id", "valuation_date", "variable", nulls_last=True)
    reasons: list[str] = []
    if robust.not_converted:
        reasons.append(
            f"MT08: {robust.not_converted} values left out because their currency has no "
            "development rate"
        )
    reasons += [f"MT08: {warning}" for warning in robust.warnings]
    small = robust.flag_rates.filter(pl.col("status") != "scored")
    if small.height:
        reasons.append(f"MT08: {_groups(small.height)} too few values to score")
    unscored = isolation.groups.filter(pl.col("status") != "scored")
    if unscored.height:
        reasons.append(f"MT09: {_groups(unscored.height)} too few claims to score")
    return AnomalyResult(flags, robust, isolation, tuple(reasons))
