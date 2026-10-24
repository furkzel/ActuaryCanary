"""Reinsurance feeds: the treaty table and the ceded movements, with the truth behind them.

The treaty table has one row per treaty, contract year and line. A treaty renews every year on
its inception date, with the same terms; a retention that moves with prices (stabilised at the
occurrence date in the simulation) is written at the price level of the inception date together
with the index series, as the data concept asks.

The ceded movements are the treaty applications of the simulation, booked the way an insurer's
bordereaux would be:

- ceded premium and reinsurance commission, per treaty, booking month, currency and line, equal
  to the sum of the ceded rows of the premiums feed (DV-RTR-11);
- ceded paid claims and changes of the ceded case reserve, per claim and treaty, booked at each
  month end on which the cumulative amount moved. They add up, claim by claim and valuation date,
  to ``ceded_paid_to_date`` and ``ceded_reserve`` of claim_valuations (DV-RTR-09): the amounts
  of the valuation file are the anchor and each treaty gets its share of them, the largest share
  taking the cents that rounding leaves over.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from actuarycanary.synthetic.claims import END_OF_TIME, ClaimWorld
from actuarycanary.synthetic.days import from_day, month_end, month_index, month_start, to_day
from actuarycanary.synthetic.feeds import date_series, id_text
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import Policies, PremiumRows
from actuarycanary.synthetic.reinsurance import Reinsurance
from actuarycanary.synthetic.scenario import Scenario, SurplusTreaty, Treaty

TREATY_COLUMNS = (
    "treaty_id",
    "treaty_type",
    "inception_date",
    "expiry_date",
    "attachment_basis",
    "loss_basis",
    "segment",
    "line",
    "entity",
    "currency",
    "cession_share",
    "retention",
    "limit",
    "number_of_lines",
    "aggregate_deductible",
    "aggregate_limit",
    "reinstatements",
    "reinstatement_rate",
    "placed_share",
    "premium_rate",
    "ceding_commission",
    "index_series",
)


@dataclass(frozen=True)
class Period:
    """One contract year of a treaty."""

    treaty_id: str
    start: int
    end: int  # exclusive


def _anniversary(inception: int, year_offset: int) -> int:
    start = from_day(inception)
    return to_day(start.replace(year=start.year + year_offset))


def contract_periods(inception: int, first_day: int, cut_off: int, treaty_id: str) -> list[Period]:
    """Annual contract periods from the inception date that end after `first_day` and start on
    or before the cut-off."""
    periods: list[Period] = []
    k = 0
    while True:
        start, end = _anniversary(inception, k), _anniversary(inception, k + 1)
        if start > cut_off:
            return periods
        if end > first_day:
            periods.append(Period(treaty_id, start, end))
        k += 1


def _treaty_rows(scenario: Scenario) -> list[tuple[str, int, list[str], dict[str, object]]]:
    """Every treaty as (id, inception day, lines, terms)."""
    rows: list[tuple[str, int, list[str], dict[str, object]]] = []
    for t in scenario.reinsurance:
        rows.append((t.treaty_id, to_day(t.inception), t.lines, _terms(t)))
    for s in scenario.phase2.surplus:
        rows.append((s.treaty_id, to_day(s.inception), s.lines, _surplus_terms(s)))
    return rows


def _terms(t: Treaty) -> dict[str, object]:
    return {
        "treaty_type": t.type,
        "loss_basis": "EVENT" if t.basis == "event" else None,
        "cession_share": t.cession,
        "retention": t.retention,
        "limit": t.limit,
        "premium_rate": t.rate_on_gross_premium if t.type == "EXCESS_OF_LOSS" else None,
        "ceding_commission": t.commission,
        "index": t.retention_indexed_to,
    }


def _surplus_terms(s: SurplusTreaty) -> dict[str, object]:
    return {
        "treaty_type": "SURPLUS",
        "loss_basis": None,
        "cession_share": None,
        "retention": s.retained_line,
        "limit": None,
        "number_of_lines": s.number_of_lines,
        "premium_rate": None,
        "ceding_commission": s.commission,
        "index": s.retention_indexed_to,
    }


def treaty_table(scenario: Scenario, market: Market, first_day: int, cut_off: int) -> pl.DataFrame:
    """The reinsurance_treaties feed: one row per treaty, contract year and line."""
    out: dict[str, list[object]] = {c: [] for c in TREATY_COLUMNS}
    reporting = scenario.meta.reporting_currency
    for treaty_id, inception, lines, terms in _treaty_rows(scenario):
        for period in contract_periods(inception, first_day, cut_off, treaty_id):
            level = (
                float(market.price_factor(np.array([period.start]))[0]) if terms["index"] else 1.0
            )
            for line in lines:
                row: dict[str, object] = {
                    "treaty_id": treaty_id,
                    "treaty_type": terms["treaty_type"],
                    "inception_date": from_day(period.start),
                    "expiry_date": from_day(period.end),
                    "attachment_basis": "LOSSES_OCCURRING",
                    "loss_basis": terms["loss_basis"],
                    "segment": scenario.lines[line].segment,
                    "line": line,
                    "entity": None,
                    "currency": reporting,
                    "cession_share": terms.get("cession_share"),
                    "retention": None
                    if terms.get("retention") is None
                    else round(float(terms["retention"]) * level, 2),  # type: ignore[arg-type]
                    "limit": None
                    if terms.get("limit") is None
                    else round(float(terms["limit"]) * level, 2),  # type: ignore[arg-type]
                    "number_of_lines": terms.get("number_of_lines"),
                    "aggregate_deductible": None,
                    "aggregate_limit": None,
                    "reinstatements": None,
                    "reinstatement_rate": None,
                    "placed_share": 1.0,
                    "premium_rate": terms.get("premium_rate"),
                    "ceding_commission": terms.get("ceding_commission"),
                    "index_series": scenario.market.cpi.series_id if terms["index"] else None,
                }
                for column in TREATY_COLUMNS:
                    out[column].append(row[column])
    schema: dict[str, pl.DataType | type] = {
        c: pl.String for c in ("treaty_id", "treaty_type", "attachment_basis", "loss_basis")
    }
    schema |= {c: pl.String for c in ("segment", "line", "entity", "currency", "index_series")}
    schema |= {c: pl.Date for c in ("inception_date", "expiry_date")}
    schema |= {
        c: pl.Float64
        for c in (
            "cession_share",
            "retention",
            "limit",
            "number_of_lines",
            "aggregate_deductible",
            "aggregate_limit",
            "reinstatements",
            "reinstatement_rate",
            "placed_share",
            "premium_rate",
            "ceding_commission",
        )
    }
    frame = pl.DataFrame(out, schema=schema)
    return frame.sort(["inception_date", "treaty_id", "line"])


# --- movements -------------------------------------------------------------------------


def premium_movements(scenario: Scenario, policies: Policies, rows: PremiumRows) -> pl.DataFrame:
    """CEDED_PREMIUM and RI_COMMISSION per treaty, booking month, currency and line."""
    ceded = np.flatnonzero(rows.treaty != "")
    if len(ceded) == 0:
        return _empty_movements()
    pol = rows.policy[ceded]
    frame = pl.DataFrame(
        {
            "treaty_id": rows.treaty[ceded].tolist(),
            "type": rows.type[ceded].tolist(),
            "month": month_index(rows.booking[ceded]),
            "currency": policies.currency[pol].tolist(),
            "line": policies.line[pol].tolist(),
            "amount": rows.amount[ceded],
        }
    )
    grouped = (
        frame.group_by(["treaty_id", "type", "month", "currency", "line"])
        .agg(pl.col("amount").sum().round(2))
        .sort(["month", "treaty_id", "type", "currency", "line"])
    )
    month = grouped["month"].to_numpy()
    segment = [scenario.lines[ln].segment for ln in grouped["line"]]
    return pl.DataFrame(
        {
            "treaty_id": grouped["treaty_id"],
            "booking_date": date_series("booking_date", month_end(month)),
            "amount": grouped["amount"],
            "currency": grouped["currency"],
            "type": grouped["type"],
            "claim_id": pl.Series([None] * grouped.height, dtype=pl.String),
            "policy_id": pl.Series([None] * grouped.height, dtype=pl.String),
            "event_code": pl.Series([None] * grouped.height, dtype=pl.String),
            "effective_date": date_series("effective_date", month_start(month)),
            "segment": segment,
            "line": grouped["line"],
        }
    )


def _empty_movements() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "treaty_id": pl.String,
            "booking_date": pl.Date,
            "amount": pl.Float64,
            "currency": pl.String,
            "type": pl.String,
            "claim_id": pl.String,
            "policy_id": pl.String,
            "event_code": pl.String,
            "effective_date": pl.Date,
            "segment": pl.String,
            "line": pl.String,
        }
    )


def _split_cents(target: np.ndarray, parts: list[np.ndarray]) -> list[np.ndarray]:
    """Shares of `target` in proportion to `parts`, each in cents, adding up to `target` exactly."""
    total = sum(parts, np.zeros(len(target)))
    anchor = np.argmax(np.stack(parts), axis=0)
    shares = [
        np.round(np.divide(p, total, out=np.zeros(len(target)), where=total > 0) * target, 2)
        for p in parts
    ]
    others = sum(
        (np.where(anchor == k, 0.0, s) for k, s in enumerate(shares)), np.zeros(len(target))
    )
    # a target without any treaty part (rounding at the limit) goes to the first treaty
    rest = np.round(target - others, 2)
    return [np.where(anchor == k, rest, s) for k, s in enumerate(shares)]


def claim_movements(
    scenario: Scenario,
    world: ClaimWorld,
    reinsurance: Reinsurance,
    valuations: pl.DataFrame,
    claim: np.ndarray,
    day: np.ndarray,
    state: dict[str, np.ndarray],
) -> pl.DataFrame:
    """CEDED_CLAIM_PAID and CEDED_CASE_RESERVE per claim, treaty and month end.

    `valuations` is the clean claim_valuations table and `claim`, `day`, `state` are the arrays it
    was built from (same order)."""
    parts = reinsurance.ceded_parts(claim, day, state["paid"], state["reserve"])
    if not parts:
        return _empty_movements()
    target_paid = valuations["ceded_paid_to_date"].to_numpy()
    target_reserve = valuations["ceded_reserve"].to_numpy()
    paid_split = _split_cents(target_paid, [p[1] for p in parts])
    reserve_split = _split_cents(target_reserve, [p[2] for p in parts])
    order = np.lexsort((day, claim))
    claim_o, day_o = claim[order], day[order]
    first = np.concatenate([[True], claim_o[1:] != claim_o[:-1]])
    pieces: list[pl.DataFrame] = []
    ids = np.array(id_text("", np.arange(1, len(world) + 1), 8), dtype=object)
    codes = np.array(world.event_codes + [None], dtype=object)
    for k, (treaty_id, _, _) in enumerate(parts):
        for kind, split in (
            ("CEDED_CLAIM_PAID", paid_split),
            ("CEDED_CASE_RESERVE", reserve_split),
        ):
            cumulative = split[k][order]
            step = np.round(cumulative - np.where(first, 0.0, np.roll(cumulative, 1)), 2)
            moved = np.flatnonzero(step != 0.0)
            if len(moved) == 0:
                continue
            who = claim_o[moved]
            pieces.append(
                pl.DataFrame(
                    {
                        "treaty_id": [treaty_id] * len(moved),
                        "booking_date": date_series("booking_date", day_o[moved]),
                        "amount": step[moved],
                        "currency": world.c_currency[who].tolist(),
                        "type": [kind] * len(moved),
                        "claim_id": ids[who].tolist(),
                        "event_code": codes[world.c_event[who]].tolist(),
                        "effective_date": date_series("effective_date", world.c_occ[who]),
                    }
                ).with_columns(
                    pl.lit(None, dtype=pl.String).alias("policy_id"),
                    pl.Series("segment", [scenario.lines[ln].segment for ln in world.c_line[who]]),
                    pl.Series("line", world.c_line[who].tolist()),
                )
            )
    if not pieces:
        return _empty_movements()
    return pl.concat(pieces).select(_empty_movements().columns)


def movements_table(premium: pl.DataFrame, claims: pl.DataFrame) -> pl.DataFrame:
    """All movements in booking order with sequential identifiers."""
    both = pl.concat([premium, claims]).sort(
        ["booking_date", "treaty_id", "type", "claim_id", "line", "currency"], nulls_last=True
    )
    ids = id_text("", np.arange(1, both.height + 1), 9)
    return both.with_columns(pl.Series("transaction_id", ids)).select(
        ["transaction_id", *both.columns]
    )


# --- truth -------------------------------------------------------------------------------


def ceded_truth(
    scenario: Scenario,
    world: ClaimWorld,
    reinsurance: Reinsurance,
    movements: pl.DataFrame,
    cut_off: int,
    first_day: int,
) -> dict[str, pl.DataFrame]:
    """Ceded and net amounts per claim and treaty (whole simulated life) and per treaty year."""
    claim = np.arange(len(world))
    end = np.full(len(world), END_OF_TIME, dtype=np.int64)
    final = world.ultimate()
    parts = reinsurance.ceded_parts(claim, end, final["paid"], np.zeros(len(world)))
    ids = np.array(id_text("", np.arange(1, len(world) + 1), 8), dtype=object)

    per_claim: list[pl.DataFrame] = []
    per_year: list[dict[str, object]] = []
    paid_cut = pl.DataFrame()
    if movements.height:
        in_cut = movements.filter(pl.col("claim_id").is_not_null())
        paid_cut = (
            in_cut.group_by(["treaty_id", "type", "claim_id"])
            .agg(pl.col("amount").sum().alias("amount"))
            .pivot(on="type", index=["treaty_id", "claim_id"], values="amount")
        )
    lines_of = {t[0]: t[2] for t in _treaty_rows(scenario)}
    inception_of = {t[0]: t[1] for t in _treaty_rows(scenario)}
    premium_year = _premium_by_year(movements)
    for treaty_id, ceded, _ in parts:
        covered = reinsurance.covered_by[treaty_id]
        hit = np.flatnonzero(covered & (ceded > 0))
        gross_final = final["paid"]
        per_claim.append(
            pl.DataFrame(
                {
                    "claim_id": ids[hit].tolist(),
                    "treaty_id": [treaty_id] * len(hit),
                    "currency": world.c_currency[hit].tolist(),
                    "gross_ultimate": np.round(gross_final[hit], 2),
                    "ceded_ultimate": np.round(ceded[hit], 2),
                    "net_ultimate_after_treaty": np.round(gross_final[hit] - ceded[hit], 2),
                }
            )
        )
        periods = contract_periods(inception_of[treaty_id], first_day, cut_off, treaty_id)
        for period in periods:
            for line in lines_of[treaty_id]:
                in_period = covered & (
                    (world.c_occ >= period.start)
                    & (world.c_occ < period.end)
                    & (world.c_line == line)
                )
                for currency in sorted(set(world.c_currency[in_period].tolist())):
                    mine = in_period & (world.c_currency == currency)
                    row = _year_row(
                        treaty_id,
                        line,
                        period,
                        currency,
                        mine,
                        ids,
                        gross_final,
                        ceded,
                        paid_cut,
                        premium_year,
                    )
                    per_year.append(row)
    claims_truth = (pl.concat(per_claim) if per_claim else pl.DataFrame()).sort(
        ["treaty_id", "claim_id"]
    )
    year_schema = {
        "treaty_id": pl.String,
        "line": pl.String,
        "contract_year": pl.Int64,
        "currency": pl.String,
        "claims_covered": pl.Int64,
        "claims_ceded": pl.Int64,
        "gross_ultimate_covered": pl.Float64,
        "ceded_ultimate": pl.Float64,
        "net_ultimate_after_treaty": pl.Float64,
        "ceded_paid_cutoff": pl.Float64,
        "ceded_reserve_cutoff": pl.Float64,
        "ceded_premium": pl.Float64,
        "ri_commission": pl.Float64,
    }
    return {
        "reinsurance_by_claim": claims_truth,
        "reinsurance_by_treaty": pl.DataFrame(per_year, schema=year_schema).sort(
            ["treaty_id", "line", "contract_year", "currency"]
        ),
    }


def _premium_by_year(movements: pl.DataFrame) -> pl.DataFrame:
    if movements.height == 0:
        return pl.DataFrame()
    return (
        movements.filter(pl.col("type").is_in(["CEDED_PREMIUM", "RI_COMMISSION"]))
        .with_columns(pl.col("effective_date").alias("when"))
        .select(["treaty_id", "line", "currency", "type", "when", "amount"])
    )


def _year_row(
    treaty_id: str,
    line: str,
    period: Period,
    currency: str,
    mine: np.ndarray,
    ids: np.ndarray,
    gross: np.ndarray,
    ceded: np.ndarray,
    paid_cut: pl.DataFrame,
    premium: pl.DataFrame,
) -> dict[str, object]:
    chosen = ids[mine].tolist()
    ceded_paid = ceded_reserve = 0.0
    if paid_cut.height:
        sub = paid_cut.filter((pl.col("treaty_id") == treaty_id) & pl.col("claim_id").is_in(chosen))
        if "CEDED_CLAIM_PAID" in sub.columns:
            ceded_paid = float(sub["CEDED_CLAIM_PAID"].fill_null(0).sum())
        if "CEDED_CASE_RESERVE" in sub.columns:
            ceded_reserve = float(sub["CEDED_CASE_RESERVE"].fill_null(0).sum())
    ceded_premium = commission = 0.0
    if premium.height:
        start, end = from_day(period.start), from_day(period.end)
        sub = premium.filter(
            (pl.col("treaty_id") == treaty_id)
            & (pl.col("line") == line)
            & (pl.col("currency") == currency)
            & (pl.col("when") >= start)
            & (pl.col("when") < end)
        )
        ceded_premium = float(sub.filter(pl.col("type") == "CEDED_PREMIUM")["amount"].sum())
        commission = float(sub.filter(pl.col("type") == "RI_COMMISSION")["amount"].sum())
    gross_sum = float(gross[mine].sum())
    ceded_sum = float(ceded[mine].sum())
    return {
        "treaty_id": treaty_id,
        "line": line,
        "contract_year": from_day(period.start).year,
        "currency": currency,
        "claims_covered": int(mine.sum()),
        "claims_ceded": int((ceded[mine] > 0).sum()),
        "gross_ultimate_covered": round(gross_sum, 2),
        "ceded_ultimate": round(ceded_sum, 2),
        "net_ultimate_after_treaty": round(gross_sum - ceded_sum, 2),
        "ceded_paid_cutoff": round(ceded_paid, 2),
        "ceded_reserve_cutoff": round(ceded_reserve, 2),
        "ceded_premium": round(ceded_premium, 2),
        "ri_commission": round(commission, 2),
    }


MONEY_COLUMNS_RI = {
    "reinsurance_by_claim": {
        c: ("row", "") for c in ("gross_ultimate", "ceded_ultimate", "net_ultimate_after_treaty")
    },
    "reinsurance_by_treaty": {
        c: ("row", "")
        for c in (
            "gross_ultimate_covered",
            "ceded_ultimate",
            "net_ultimate_after_treaty",
            "ceded_paid_cutoff",
            "ceded_reserve_cutoff",
            "ceded_premium",
            "ri_commission",
        )
    },
}
