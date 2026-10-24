"""The ORIGINAL currency view of a run (CV01, record 0225).

In the ORIGINAL view nothing is converted and amounts of different currencies are never
added. A run reads it by giving every claim and every policy a line of its own per currency:
`MOTOR_OD` with claims in TRY and USD becomes the lines `MOTOR_OD [TRY]` and `MOTOR_OD [USD]`.
Triangles, methods, measures and the report then keep the currencies apart without any rule
of their own, and every rate is 1.

FUNCTIONAL is not a view of its own: version 1.0 has no entity feed that names a functional
currency, so CV01 keeps it equal to REPORTING.
"""

import polars as pl

from actuarycanary.convert.currency import IDENTITY_TARGET
from actuarycanary.convert.rates import DevelopmentRates

REPORTING = "REPORTING"
ORIGINAL = "ORIGINAL"
VIEWS = (REPORTING, ORIGINAL)
UNIT_LABEL = IDENTITY_TARGET  # what stands where the report names the reporting currency


def line_in(line: str | None, currency: str) -> str:
    return f"{line or 'UNKNOWN'} [{currency}]"


def currency_of(line: str) -> str:
    """The currency a line of the ORIGINAL view stands for ("" for a line without one)."""
    return line[line.rindex("[") + 1 : -1] if line.endswith("]") and "[" in line else ""


def split_claims(claims: pl.DataFrame, valuations: pl.DataFrame) -> pl.DataFrame:
    """The claims with `line` made per currency of the claim (its valuations carry it; the
    currency is one per claim, DV-CLV-12). A claim without a known currency keeps its line."""
    if "line" not in claims.columns:
        return claims
    currency = (
        valuations.filter(pl.col("currency").is_not_null() & (pl.col("currency") != "UNKNOWN"))
        .group_by("claim_id", maintain_order=True)
        .agg(pl.col("currency").first().alias("_currency"))
    )
    joined = claims.join(currency, on="claim_id", how="left", maintain_order="left")
    suffixed = pl.format("{} [{}]", pl.col("line").fill_null("UNKNOWN"), pl.col("_currency"))
    return joined.with_columns(
        pl.when(pl.col("_currency").is_not_null())
        .then(suffixed)
        .otherwise(pl.col("line"))
        .alias("line")
    ).drop("_currency")


def split_policies(policies: pl.DataFrame) -> pl.DataFrame:
    """The policies with `line` made per currency of the policy."""
    if "line" not in policies.columns or "currency" not in policies.columns:
        return policies
    known = pl.col("currency").is_not_null() & (pl.col("currency") != "UNKNOWN")
    suffixed = pl.format("{} [{}]", pl.col("line").fill_null("UNKNOWN"), pl.col("currency"))
    return policies.with_columns(
        pl.when(known).then(suffixed).otherwise(pl.col("line")).alias("line")
    )


def identity_rates(currencies: list[str]) -> DevelopmentRates:
    """Rate 1 for every currency: amounts stay as they are."""
    return DevelopmentRates({c: 1.0 for c in currencies}, None)
