"""Recovery flows in one structure, whichever their source (recoveries spec, decision 0203).

With a recoveries feed the bookings are the flows. Without one, the subrogation and salvage
flows are derived from the to-date fields of claim valuations: the increment between consecutive
valuations of a claim, booked on the later valuation date. When both exist the transactions win
and the differences to the to-date fields are listed (DV-RCV-08).
"""

from dataclasses import dataclass

import polars as pl

from actuarycanary.canonical.feeds import UNKNOWN, Finding, finding
from actuarycanary.io.excel import SOURCE_COLUMNS, SOURCE_ROW

SUBROGATION = "RECOVERY_SUBROGATION"
SALVAGE = "RECOVERY_SALVAGE"
OTHER = "RECOVERY_OTHER"
# the to-date field of claim valuations behind each recovery type; RECOVERY_OTHER has none
TO_DATE_FIELDS = {SUBROGATION: "subrogation_to_date", SALVAGE: "salvage_to_date"}
TRANSACTIONS = "transactions"
DERIVED = "derived"
NONE = "none"
DERIVED_COLUMN = "derived"
DERIVED_RULE = "CV04-DERIVED"  # finding written when the flows were derived from to-date fields
# amounts are stored to the cent; a sum of bookings and a to-date field that differ by less than
# this are the same amount (record 0384)
AMOUNT_TOLERANCE = 0.05
FLOW_COLUMNS = ("transaction_id", "claim_id", "booking_date", "amount", "currency", "type")
_SHORT = {SUBROGATION: "SUB", SALVAGE: "SAL"}


@dataclass(frozen=True)
class Recoveries:
    """The recovery flows a run works with. `frame` has the columns of the recoveries feed plus
    `derived` (true on every row when the flows come from the to-date fields)."""

    frame: pl.DataFrame
    source: str  # TRANSACTIONS, DERIVED or NONE
    types: tuple[str, ...]  # recovery types the source can show
    note: str  # one sentence on the source, for the report
    findings: tuple[Finding, ...] = ()

    @property
    def available(self) -> bool:
        return self.source != NONE


def to_date_fields(valuations: pl.DataFrame) -> dict[str, str]:
    """Recovery type -> to-date column, for the columns `valuations` carries."""
    return {kind: name for kind, name in TO_DATE_FIELDS.items() if name in valuations.columns}


def derive_recoveries(valuations: pl.DataFrame) -> pl.DataFrame:
    """Recovery flows from the to-date fields: per claim and type the increment between
    consecutive valuations, booked on the later valuation date; the first valuation counts from
    zero. A negative increment is a reversal and is kept; a zero increment is no flow. An empty
    to-date amount is read as no change (the amount before it stands)."""
    fields = to_date_fields(valuations)
    source = [c for c in SOURCE_COLUMNS if c in valuations.columns]
    parts = []
    ordered = valuations.sort("claim_id", "valuation_date")
    for kind, name in fields.items():
        level = pl.col(name).forward_fill().over("claim_id").fill_null(0.0)
        step = level - level.shift(1).over("claim_id").fill_null(0.0)
        flows = ordered.with_columns(step.alias("amount")).filter(pl.col("amount") != 0)
        month = pl.col("valuation_date").dt.strftime("%Y%m")
        parts.append(
            flows.select(
                pl.format("DERIVED-{}-{}-{}", "claim_id", month, pl.lit(_SHORT[kind])).alias(
                    "transaction_id"
                ),
                "claim_id",
                pl.col("valuation_date").alias("booking_date"),
                pl.col("amount").round(2),
                pl.col("currency").fill_null(UNKNOWN)
                if "currency" in flows.columns
                else pl.lit(UNKNOWN).alias("currency"),
                pl.lit(kind).alias("type"),
                *source,
            )
        )
    if not parts:
        return _empty(source)
    return pl.concat(parts).sort("claim_id", "booking_date", "type")


def _empty(source: list[str]) -> pl.DataFrame:
    schema: dict[str, pl.DataType] = {
        "transaction_id": pl.String(),
        "claim_id": pl.String(),
        "booking_date": pl.Date(),
        "amount": pl.Float64(),
        "currency": pl.String(),
        "type": pl.String(),
    }
    schema |= {c: pl.Int64() if c == SOURCE_ROW else pl.String() for c in source}
    return pl.DataFrame(schema=schema)


def cumulative_at(valuations: pl.DataFrame, flows: pl.DataFrame, name: str) -> pl.DataFrame:
    """Per valuation row of a claim: the sum of `flows` booked on or before its valuation date,
    as column `name` beside claim_id and valuation_date."""
    grid = valuations.select("claim_id", "valuation_date").unique().sort("valuation_date")
    steps = (
        flows.group_by("claim_id", "booking_date")
        .agg(pl.col("amount").sum())
        .sort("claim_id", "booking_date")
        .with_columns(pl.col("amount").cum_sum().over("claim_id").alias(name))
        .sort("booking_date")
    )
    joined = grid.join_asof(
        steps,
        left_on="valuation_date",
        right_on="booking_date",
        by="claim_id",
        strategy="backward",
        check_sortedness=False,
    )
    return joined.select("claim_id", "valuation_date", pl.col(name).fill_null(0.0))


def recovery_differences(recoveries: pl.DataFrame, valuations: pl.DataFrame) -> pl.DataFrame:
    """DV-RCV-08: where the bookings of a claim and type accumulated to a valuation date differ
    from the to-date field of that valuation. One row per claim, type and valuation date, with
    both values and the source columns of the valuation row."""
    source = [c for c in SOURCE_COLUMNS if c in valuations.columns]
    parts = []
    for kind, name in to_date_fields(valuations).items():
        flows = recoveries.filter(pl.col("type") == kind)
        booked = cumulative_at(valuations, flows, "booked")
        both = valuations.filter(pl.col(name).is_not_null()).join(
            booked, on=["claim_id", "valuation_date"], how="left"
        )
        gap = pl.col("booked").fill_null(0.0) - pl.col(name)
        parts.append(
            both.filter(gap.abs() > AMOUNT_TOLERANCE).select(
                "claim_id",
                pl.lit(kind).alias("type"),
                "valuation_date",
                pl.col("booked").fill_null(0.0).alias("booked"),
                pl.col(name).alias("to_date"),
                gap.alias("difference"),
                *source,
            )
        )
    if not parts:
        return pl.DataFrame(
            schema={
                "claim_id": pl.String(),
                "type": pl.String(),
                "valuation_date": pl.Date(),
                "booked": pl.Float64(),
                "to_date": pl.Float64(),
                "difference": pl.Float64(),
            }
        )
    return pl.concat(parts).sort("claim_id", "type", "valuation_date")


def _with_claim_currency(recoveries: pl.DataFrame, valuations: pl.DataFrame) -> pl.DataFrame:
    """DV-RCV-03: a booking without a valid currency takes the currency of its claim."""
    if "currency" not in valuations.columns:
        return recoveries
    of_claim = (
        valuations.filter(pl.col("currency").is_not_null() & (pl.col("currency") != UNKNOWN))
        .group_by("claim_id")
        .agg(pl.col("currency").last().alias("_claim_currency"))
    )
    filled = recoveries.join(of_claim, on="claim_id", how="left").with_columns(
        pl.when((pl.col("currency") == UNKNOWN) & pl.col("_claim_currency").is_not_null())
        .then(pl.col("_claim_currency"))
        .otherwise(pl.col("currency"))
        .alias("currency")
    )
    return filled.drop("_claim_currency")


def build_recoveries(feed: pl.DataFrame | None, valuations: pl.DataFrame) -> Recoveries:
    """The recovery flows of a run. `feed` is the canonical recoveries feed, or None when no
    recoveries file was loaded; `valuations` is the canonical claim_valuations feed."""
    fields = to_date_fields(valuations)
    if feed is not None:
        frame = _with_claim_currency(feed, valuations).with_columns(
            pl.lit(False).alias(DERIVED_COLUMN)
        )
        note = "recovery transactions (recoveries feed)"
        if fields:
            note += "; the to-date recovery fields of claim valuations are not used"
        return Recoveries(frame, TRANSACTIONS, (SUBROGATION, SALVAGE, OTHER), note)
    if not fields:
        return Recoveries(
            _empty([]).with_columns(pl.lit(True).alias(DERIVED_COLUMN)),
            NONE,
            (),
            "no recoveries feed and no to-date recovery column in claim valuations",
        )
    frame = derive_recoveries(valuations).with_columns(pl.lit(True).alias(DERIVED_COLUMN))
    names = " and ".join(fields.values())
    note = (
        f"derived from {names} of claim valuations (no recoveries feed): one flow per claim, "
        "type and valuation month; other recoveries are not available"
    )
    found = finding(
        "recoveries",
        DERIVED_RULE,
        "INFO",
        f"recovery flows derived from {names} of claim_valuations, one per claim, type and "
        "valuation month (no recoveries feed was loaded)",
        frame,
    )
    return Recoveries(frame, DERIVED, tuple(fields), note, (found,) if found else ())
