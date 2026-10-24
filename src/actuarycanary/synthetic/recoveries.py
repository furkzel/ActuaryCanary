"""Recovery bookings (subrogation and salvage) and their truth.

The simulation already gives every claim at most one subrogation and one salvage recovery, with
the day it is received. A booking is one row of the recoveries feed; the cumulative bookings of
a claim up to a valuation date equal ``subrogation_to_date`` and ``salvage_to_date`` of
claim_valuations (DV-RCV-08). Recoveries received after the cut-off are in the truth only.
"""

import numpy as np
import polars as pl

from actuarycanary.synthetic.claims import ClaimWorld
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.feeds import date_series, id_text
from actuarycanary.synthetic.scenario import Scenario

INSURER_SHARE = 0.7  # of subrogation recoveries paid by another insurer (the rest by other parties)


def recovery_tables(
    scenario: Scenario, world: ClaimWorld, streams: Streams
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The recoveries feed (bookings up to the cut-off) and the truth of every recovery."""
    cut_off = to_day(scenario.meta.valuation.last)
    kinds = (
        ("RECOVERY_SUBROGATION", world.v_subrogation),
        ("RECOVERY_SALVAGE", world.v_salvage),
    )
    claim_parts, day_parts, amount_parts, type_parts = [], [], [], []
    for kind, amount in kinds:
        hit = np.flatnonzero(amount > 0)
        claim_parts.append(world.v_claim[hit])
        day_parts.append(world.v_day[hit])
        amount_parts.append(amount[hit])
        type_parts.append(np.full(len(hit), kind, dtype=object))
    claim = np.concatenate(claim_parts)
    day = np.concatenate(day_parts)
    amount = np.concatenate(amount_parts)
    kind = np.concatenate(type_parts)
    order = np.lexsort((kind, claim, day))
    claim, day, amount, kind = claim[order], day[order], amount[order], kind[order]

    rng = streams.get("phase2", "recoveries", "counterparty")
    draw = rng.random(len(claim))
    counterparty = np.where(
        kind == "RECOVERY_SALVAGE",
        "SALVAGE_BUYER",
        np.where(draw < INSURER_SHARE, "INSURER", "OTHER_PARTY"),
    )
    ids = np.array(id_text("", np.arange(1, len(world) + 1), 8), dtype=object)
    booked = day <= cut_off
    last_pay = np.maximum(world.c_e0, np.where(world.has_reopen, world.c_e1, 0))

    full = pl.DataFrame(
        {
            "claim_id": ids[claim].tolist(),
            "type": kind.tolist(),
            "booking_date": date_series("booking_date", day),
            "amount": np.round(amount, 2),
            "currency": world.c_currency[claim].tolist(),
            "counterparty_type": counterparty.tolist(),
            "days_after_last_payment": day - last_pay[claim],
            "booked_by_cutoff": booked,
        }
    )
    feed = full.filter(pl.col("booked_by_cutoff")).drop(
        "days_after_last_payment", "booked_by_cutoff"
    )
    feed = feed.with_columns(
        pl.Series("transaction_id", id_text("", np.arange(1, feed.height + 1), 9))
    ).select(
        [
            "transaction_id",
            "claim_id",
            "booking_date",
            "amount",
            "currency",
            "type",
            "counterparty_type",
        ]
    )
    truth = full.rename({"amount": "recovery_amount", "booking_date": "recovery_date"})
    return feed, truth


MONEY_COLUMNS_RECOVERIES = {"recoveries_truth": {"recovery_amount": ("row", "")}}
