"""Inputs of the treaty application (MT21) assembled from the canonical feeds of a run.

The run's gross claims (claim_valuations with claims and policies), the treaties, the market
(price indices and exchange rates), the written premium and the policy-level facultative
movements become the sections, the claim book and the options of `apply_programme`
(decisions 0400 to 0403).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.convert.currency import MAX_LOOKBACK_DAYS
from actuarycanary.convert.market import FX_SPOT, MarketData
from actuarycanary.methods.reinsurance.application import (
    Application,
    ClaimBook,
    Options,
    apply_programme,
)
from actuarycanary.methods.reinsurance.index import PAYMENT_BY_PAYMENT, FxLookup, price_indices
from actuarycanary.methods.reinsurance.premium import PremiumApplication, apply_premium
from actuarycanary.methods.reinsurance.terms import (
    FACULTATIVE,
    Excluded,
    Section,
    sections_from_frame,
)
from actuarycanary.structures.premium import WRITTEN_TYPES

TREATIES = "reinsurance_treaties"
MOVEMENTS = "reinsurance_transactions"
CEDED_PREMIUM = "CEDED_PREMIUM"


@dataclass(frozen=True)
class ReinsuranceInputs:
    sections: list[Section]
    excluded: list[Excluded]
    book: ClaimBook | None
    options: Options
    premium: PremiumApplication | None
    written: pl.DataFrame | None
    movements: pl.DataFrame | None
    notes: list[str] = field(default_factory=list)


def fx_lookup(market: pl.DataFrame | None) -> FxLookup | None:
    """Spot rate of a pair at a date: the rate of the day or the latest one before it within
    the lookback of CV01, direct or by reciprocal."""
    if market is None or market.height == 0:
        return None
    data = MarketData.from_frame(market)
    tables: dict[tuple[str, str], tuple[np.ndarray, np.ndarray] | None] = {}

    def rate(original: str, target: str, day: date) -> float | None:
        if original == target:
            return 1.0
        key = (original, target)
        if key not in tables:
            pair = data.pair(FX_SPOT, original, target)
            tables[key] = (
                None
                if pair is None
                else (pair["key"].to_numpy().astype("datetime64[D]"), pair["rate"].to_numpy())
            )
        table = tables[key]
        if table is None:
            return None
        days, values = table
        at = np.datetime64(day, "D")
        i = int(np.searchsorted(days, at, side="right")) - 1
        if i < 0 or at - days[i] > np.timedelta64(MAX_LOOKBACK_DAYS, "D"):
            return None
        return float(values[i])

    return rate


def gross_book(frames: Mapping[str, pl.DataFrame]) -> ClaimBook | None:
    """Gross paid and incurred per claim and valuation date, with the claim and policy
    attributes the scope rules need; None without claim valuations."""
    valuations = frames.get("claim_valuations")
    if valuations is None or valuations.height == 0:
        return None
    reserve = (
        pl.col("case_reserve").fill_null(0.0)
        if "case_reserve" in valuations.columns
        else pl.lit(0.0)
    )
    rows = (
        valuations.filter(pl.col("claim_id").is_not_null() & pl.col("valuation_date").is_not_null())
        .with_columns(
            pl.col("paid_to_date").fill_null(0.0).cast(pl.Float64).alias("paid"),
            (pl.col("paid_to_date").fill_null(0.0) + reserve).cast(pl.Float64).alias("incurred"),
        )
        .unique(["claim_id", "valuation_date"], keep="last", maintain_order=True)
    )
    claims = frames.get("claims")
    currency = (
        rows.filter(pl.col("currency").is_not_null())
        .group_by("claim_id")
        .agg(pl.col("currency").first())
        if "currency" in rows.columns
        else pl.DataFrame(schema={"claim_id": pl.String, "currency": pl.String})
    )
    if claims is None:
        claims = rows.select("claim_id").unique()
    keep = [
        c
        for c in (
            "claim_id",
            "occurrence_date",
            "event_code",
            "policy_id",
            "line",
            "segment",
            "entity",
        )
        if c in claims.columns
    ]
    attributes = (
        claims.select(keep)
        .unique("claim_id", keep="first")
        .join(currency, on="claim_id", how="left")
    )
    return ClaimBook(
        rows.select(["claim_id", "valuation_date", "paid", "incurred"]),
        attributes,
        frames.get("policies"),
    )


def written_premium(frames: Mapping[str, pl.DataFrame]) -> pl.DataFrame | None:
    """Gross written premium transactions (PR01 types) with the policy attributes."""
    premiums, policies = frames.get("premiums"), frames.get("policies")
    if premiums is None or policies is None or "type" not in premiums.columns:
        return None
    wanted = [
        c
        for c in ("policy_id", "start_date", "end_date", "line", "segment", "entity", "sum_insured")
        if c in policies.columns
    ]
    pol = policies.select(wanted).unique("policy_id", keep="first")
    keep = [c for c in ("policy_id", "booking_date", "amount", "currency") if c in premiums.columns]
    return (
        premiums.filter(pl.col("type").is_in(WRITTEN_TYPES) & pl.col("amount").is_not_null())
        .select(keep)
        .join(pol, on="policy_id", how="left")
    )


def facultative_shares(
    sections: list[Section], movements: pl.DataFrame | None, written: pl.DataFrame | None
) -> dict[tuple[str, str], float]:
    """Share of each policy under a facultative treaty: `cession_share` when the row gives it,
    else the policy's ceded premium of the treaty over its gross written premium (0400)."""
    fac = {s.treaty_id: s for s in sections if s.treaty_type == FACULTATIVE}
    if not fac or movements is None or "policy_id" not in movements.columns:
        return {}
    ceded = (
        movements.filter(
            pl.col("treaty_id").is_in(list(fac))
            & pl.col("policy_id").is_not_null()
            & (pl.col("type") == CEDED_PREMIUM)
        )
        .group_by(["treaty_id", "policy_id"])
        .agg(pl.col("amount").sum())
    )
    gross = (
        written.group_by("policy_id").agg(pl.col("amount").sum().alias("gross"))
        if written is not None
        else pl.DataFrame(schema={"policy_id": pl.String, "gross": pl.Float64})
    )
    out: dict[tuple[str, str], float] = {}
    for row in ceded.join(gross, on="policy_id", how="left").iter_rows(named=True):
        given = fac[row["treaty_id"]].cession_share
        share = (
            given if given is not None else (row["amount"] / row["gross"] if row["gross"] else None)
        )
        if share is not None:
            out[(row["treaty_id"], str(row["policy_id"]))] = float(min(max(share, 0.0), 1.0))
    return out


def assemble(
    frames: Mapping[str, pl.DataFrame],
    index_clause: str = PAYMENT_BY_PAYMENT,
    sections: list[Section] | None = None,
) -> ReinsuranceInputs:
    """Everything the application needs from a run's canonical frames. `sections` replaces the
    loaded programme (the what-if of MT21)."""
    excluded: list[Excluded] = []
    if sections is None:
        treaties = frames.get(TREATIES)
        sections, excluded = sections_from_frame(treaties) if treaties is not None else ([], [])
    market = frames.get("market")
    indices = price_indices(market)
    fx = fx_lookup(market)
    movements = frames.get(MOVEMENTS)
    written = written_premium(frames)
    shares = facultative_shares(sections, movements, written)
    premium = (
        apply_premium(sections, written, price_index=indices, fx=fx, facultative_shares=shares)
        if written is not None
        else None
    )
    notes: list[str] = []
    if premium is None:
        notes.append(
            "no premiums with policies: no premium side, no stop loss, no reinstatement premium"
        )
    options = Options(
        index_clause=index_clause,
        price_index=indices,
        fx=fx,
        facultative_shares=shares,
        earned_premium=premium.earned_premium() if premium else {},
        deposit_premium=premium.deposit_premium() if premium else {},
    )
    return ReinsuranceInputs(
        sections, excluded, gross_book(frames), options, premium, written, movements, notes
    )


def apply(inputs: ReinsuranceInputs) -> Application | None:
    """The programme applied to the run's gross claims at every valuation date held."""
    if inputs.book is None:
        return None
    return apply_programme(inputs.sections, inputs.book, inputs.options, inputs.excluded)
