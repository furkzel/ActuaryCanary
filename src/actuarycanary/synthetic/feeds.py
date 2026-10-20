"""The six feeds of the version 1.0 input set as clean tables (polars), before faults and mess.

Column names, order and meaning follow spec/data/. Dates are dates, identifiers are text.
"""

import numpy as np
import polars as pl

from actuarycanary.synthetic.claims import (
    CLOSED,
    CLOSED_NIL,
    STATUS_NAMES,
    ClaimWorld,
    month_positions,
)
from actuarycanary.synthetic.days import month_end, month_index, month_start, to_day
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import (
    NO_DAY,
    WRITTEN_TYPES,
    Policies,
    PremiumRows,
    first_valuation_month,
)
from actuarycanary.synthetic.reinsurance import Reinsurance
from actuarycanary.synthetic.scenario import Scenario, SizeSpec

FEEDS = ("claim_valuations", "claims", "policies", "premiums", "expenses", "market")


def id_text(prefix: str, numbers: np.ndarray, width: int) -> list[str]:
    """Identifiers as zero-padded text, so leading zeros must survive a round trip."""
    return [f"{prefix}{n:0{width}d}" for n in numbers]


def date_series(name: str, days: np.ndarray, missing: np.ndarray | None = None) -> pl.Series:
    """A Date column from day numbers; `missing` marks cells left empty."""
    values = (
        pl.Series(name, np.where(missing, 0, days) if missing is not None else days)
        .cast(pl.Int32)
        .cast(pl.Date)
    )
    if missing is not None and missing.any():
        values = pl.select(
            pl.when(pl.Series(missing).not_()).then(values).otherwise(None).alias(name)
        ).to_series()
    return values


def claim_ids(world: ClaimWorld) -> np.ndarray:
    return np.array(id_text("", np.arange(1, len(world) + 1), 8), dtype=object)


def valuation_rows(
    world: ClaimWorld, reinsurance: Reinsurance, scenario: Scenario, size: SizeSpec
) -> tuple[pl.DataFrame, np.ndarray, np.ndarray]:
    """claim_valuations as the insurer would extract it: one row per claim and month end."""
    cut_off = to_day(scenario.meta.valuation.last)
    first, last = month_positions(world, cut_off)
    first = np.maximum(first, first_valuation_month(scenario, size))
    rows = np.maximum(last - first + 1, 0)
    claim = np.repeat(np.arange(len(world)), rows)
    offset = np.arange(len(claim)) - np.repeat(np.cumsum(rows) - rows, rows)
    day = month_end(first[claim] + offset)
    order = np.lexsort((claim, day))
    claim, day = claim[order], day[order]
    state = world.state(claim, day)
    ceded_paid, ceded_reserve = reinsurance.ceded(claim, day, state["paid"], state["reserve"])
    ceded_paid = np.minimum(ceded_paid, state["paid"])
    ceded_reserve = np.minimum(ceded_reserve, state["reserve"])
    status = np.array([STATUS_NAMES[s] for s in range(5)], dtype=object)[state["status"]]
    ids = claim_ids(world)
    frame = pl.DataFrame(
        {
            "claim_id": ids[claim].tolist(),
            "valuation_date": date_series("valuation_date", day),
            "paid_to_date": np.round(state["paid"], 2),
            "case_reserve": np.round(state["reserve"], 2),
            "status": status.tolist(),
            "currency": world.c_currency[claim].tolist(),
            "subrogation_to_date": np.round(state["subrogation"], 2),
            "salvage_to_date": np.round(state["salvage"], 2),
            "expense_allocated_to_date": np.round(state["expense"], 2),
            "ceded_paid_to_date": np.round(ceded_paid, 2),
            "ceded_reserve": np.round(ceded_reserve, 2),
        }
    )
    return frame, claim, day


def claims_table(world: ClaimWorld, scenario: Scenario) -> pl.DataFrame:
    cut_off = to_day(scenario.meta.valuation.last)
    reported = np.flatnonzero(world.c_rep <= cut_off)
    policies = world.policies
    pol = world.c_policy[reported]
    segment = np.array([scenario.lines[ln].segment for ln in world.c_line[reported]], dtype=object)
    # the date the claim was last closed by the cut-off; empty while it is open or reopened
    at_cut_off = world.state(reported, np.full(len(reported), cut_off))["status"]
    closed_now = np.isin(at_cut_off, (CLOSED, CLOSED_NIL))
    reopened_and_closed = world.has_reopen[reported] & (world.c_e1[reported] <= cut_off)
    last_close = np.where(reopened_and_closed, world.c_e1[reported], world.c_e0[reported])
    event_code = np.array(
        [world.event_codes[e] if e >= 0 else None for e in world.c_event[reported]], dtype=object
    )
    return pl.DataFrame(
        {
            "claim_id": claim_ids(world)[reported].tolist(),
            "occurrence_date": date_series("occurrence_date", world.c_occ[reported]),
            "report_date": date_series("report_date", world.c_rep[reported]),
            "segment": segment.tolist(),
            "line": world.c_line[reported].tolist(),
            "entity": world.c_entity[reported].tolist(),
            "policy_id": policies.policy_id[pol].tolist(),
            "product": policies.product[pol].tolist(),
            "partner": policies.partner[pol].tolist(),
            "cause": world.c_cause[reported].tolist(),
            "close_date": date_series(
                "close_date", np.where(closed_now, last_close, 0), ~closed_now
            ),
            "event_code": event_code.tolist(),
        }
    )


def policies_table(policies: Policies, scenario: Scenario) -> pl.DataFrame:
    segment = np.array([scenario.lines[ln].segment for ln in policies.line], dtype=object)
    no_cancel = policies.cancel == NO_DAY
    return pl.DataFrame(
        {
            "policy_id": policies.policy_id.tolist(),
            "start_date": date_series("start_date", policies.start),
            "end_date": date_series("end_date", policies.end),
            "segment": segment.tolist(),
            "line": policies.line.tolist(),
            "currency": policies.currency.tolist(),
            "entity": policies.entity.tolist(),
            "product": policies.product.tolist(),
            "partner": policies.partner.tolist(),
            "channel": policies.channel.tolist(),
            "issue_date": date_series("issue_date", policies.issue),
            "cancellation_date": date_series(
                "cancellation_date", np.where(no_cancel, 0, policies.cancel), no_cancel
            ),
            "sum_insured": pl.Series(
                "sum_insured", np.where(policies.sum_insured > 0, policies.sum_insured, np.nan)
            ).fill_nan(None),
            "exposure_units": policies.units,
        }
    )


def premiums_table(policies: Policies, rows: PremiumRows) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "transaction_id": id_text("", np.arange(1, len(rows) + 1), 9),
            "policy_id": policies.policy_id[rows.policy].tolist(),
            "booking_date": date_series("booking_date", rows.booking),
            "amount": rows.amount,
            "currency": policies.currency[rows.policy].tolist(),
            "type": rows.type.tolist(),
            "effective_date": date_series("effective_date", rows.effective),
        }
    )


# --- earned premium and expenses ---------------------------------------------------------


def earned_premium(
    policies: Policies,
    rows: PremiumRows,
    lines: list[str],
    entities: list[str],
    currencies: list[str],
) -> tuple[np.ndarray, int, int]:
    """Gross earned premium per (line, entity, currency) group and calendar month.

    Each written-type transaction earns evenly by day from its effective date to the policy
    end (PR02). Returns an array (groups, months) in original currency, with the groups
    ordered line-major (line, entity, currency), plus the first and last month index.
    """
    written = np.isin(rows.type, WRITTEN_TYPES)
    pol = rows.policy[written]
    a = np.maximum(rows.effective[written], policies.start[pol])
    b = policies.end[pol]
    keep = b > a
    pol, a, b, amount = pol[keep], a[keep], b[keep], rows.amount[written][keep]
    group = (
        np.array([lines.index(x) for x in policies.line], dtype=np.int64)[pol]
        * (len(entities) * len(currencies))
        + np.array([entities.index(x) for x in policies.entity], dtype=np.int64)[pol]
        * len(currencies)
        + np.array([currencies.index(x) for x in policies.currency], dtype=np.int64)[pol]
    )
    d0, d1 = int(a.min()), int(b.max()) - 1  # the end day is excluded from cover
    n_groups = len(lines) * len(entities) * len(currencies)
    diff = np.zeros((n_groups, d1 - d0 + 3))
    rate = amount / (b - a)
    np.add.at(diff, (group, a - d0), rate)
    np.add.at(diff, (group, b - d0), -rate)
    daily = np.cumsum(diff, axis=1)[:, : d1 - d0 + 1]
    m0, m1 = int(month_index(d0)), int(month_index(d1))
    month_of_day = month_index(d0 + np.arange(d1 - d0 + 1)) - m0
    monthly = np.stack(
        [
            np.bincount(month_of_day, weights=daily[g], minlength=m1 - m0 + 1)
            for g in range(n_groups)
        ]
    )
    return monthly, m0, m1


def expenses_table(
    scenario: Scenario,
    size: SizeSpec,
    market: Market,
    world: ClaimWorld,
    policies: Policies,
    rows: PremiumRows,
    streams,
) -> pl.DataFrame:
    """Monthly expense bookings in reporting currency: administration, acquisition, claims
    handling (a share of payments) and other costs (per entity, no line)."""
    cut_off = to_day(scenario.meta.valuation.last)
    lines = list(scenario.lines)
    entities = [e.id for e in scenario.entities]
    currencies = sorted(
        set(policies.currency.tolist()), key=lambda c: (c != scenario.meta.reporting_currency, c)
    )
    monthly, m0, _ = earned_premium(policies, rows, lines, entities, currencies)
    first_month = first_valuation_month(scenario, size)
    last_month = int(month_index(cut_off))
    months = np.arange(first_month, last_month + 1)
    n_c, n_e = len(currencies), len(entities)

    def to_reporting(series: np.ndarray, currency: str) -> np.ndarray:
        if currency == scenario.meta.reporting_currency:
            return series
        mid = month_start(months) + 14
        return series * market.fx_at(currency, mid)

    out: dict[str, list] = {
        "period": [],
        "amount": [],
        "currency": [],
        "type": [],
        "entity": [],
        "segment": [],
        "line": [],
    }

    def book(kind: str, amounts: np.ndarray, entity: str | None, line: str | None) -> None:
        amounts = np.round(amounts, 2)
        keep = amounts != 0
        count = int(keep.sum())
        out["period"].append(month_end(months)[keep])
        out["amount"].append(amounts[keep])
        out["currency"] += [scenario.meta.reporting_currency] * count
        out["type"] += [kind] * count
        out["entity"] += [entity] * count
        out["segment"] += [scenario.lines[line].segment if line else None] * count
        out["line"] += [line] * count

    earned_try: dict[tuple[str, str], np.ndarray] = {}
    for li, ln in enumerate(lines):
        for ei, entity in enumerate(entities):
            total = np.zeros(len(months))
            for ci, currency in enumerate(currencies):
                series = monthly[(li * n_e + ei) * n_c + ci]
                picked = series[months - m0] if len(series) else np.zeros(len(months))
                total += to_reporting(
                    np.where((months >= m0) & (months - m0 < len(series)), picked, 0.0), currency
                )
            earned_try[(ln, entity)] = total

    payments = world.p_day <= cut_off
    pay_month = month_index(world.p_day[payments]) - first_month
    pay_try = world.p_amount[payments].copy()
    for code in market.fx:
        foreign = world.c_currency[world.p_claim[payments]] == code
        pay_try[foreign] *= market.fx_at(code, world.p_day[payments][foreign])
    pay_line = world.c_line[world.p_claim[payments]]
    pay_entity = world.c_entity[world.p_claim[payments]]
    inside = (pay_month >= 0) & (pay_month < len(months))
    for ln, line in scenario.lines.items():
        for entity in line.entities:
            earned = earned_try[(ln, entity)]
            book("ADMINISTRATION", scenario.expenses.administration_share[ln] * earned, entity, ln)
            book("ACQUISITION", scenario.expenses.acquisition_share[ln] * earned, entity, ln)
            sel = inside & (pay_line == ln) & (pay_entity == entity)
            handled = np.bincount(pay_month[sel], weights=pay_try[sel], minlength=len(months))
            book(
                "CLAIMS_HANDLING_UNALLOCATED",
                scenario.expenses.unallocated_claims_handling_share_of_paid * handled,
                entity,
                ln,
            )
    for entity in entities:
        total = sum((v for (ln, e), v in earned_try.items() if e == entity), np.zeros(len(months)))
        book("OTHER", scenario.expenses.other_share_of_earned * total, entity, None)
    period = np.concatenate(out["period"])
    order = np.lexsort(
        (
            np.array(out["line"], dtype=object).astype(str),
            np.array(out["entity"], dtype=object).astype(str),
            np.array(out["type"]),
            period,
        )
    )
    amount = np.concatenate(out["amount"])
    pick = lambda values: np.array(values, dtype=object)[order].tolist()  # noqa: E731
    return pl.DataFrame(
        {
            "period": date_series("period", period[order]),
            "amount": amount[order],
            "currency": pick(out["currency"]),
            "type": pick(out["type"]),
            "entity": pick(out["entity"]),
            "segment": pick(out["segment"]),
            "line": pick(out["line"]),
        }
    )


# --- market ---------------------------------------------------------------------------


def market_sheets(scenario: Scenario, market: Market) -> dict[str, pl.DataFrame]:
    """The market file: one sheet of exchange rates, one of the price index."""
    cut_off = to_day(scenario.meta.valuation.last)
    days = np.arange(market.base_day, cut_off + 1)
    months = np.arange(int(month_index(market.base_day)), int(month_index(cut_off)) + 1)
    ends = month_end(months)
    weekday = ((days + 3) % 7) < 5
    sheets: dict[str, pl.DataFrame] = {}
    parts: list[pl.DataFrame] = []
    kinds = scenario.market.fx_kinds_written
    for pair in scenario.market.fx:
        code = pair.series_id.split("/")[0]
        rates = market.fx[code]
        if "FX_SPOT" in kinds:
            parts.append(
                _series_frame(
                    pair.series_id, days[weekday], rates[days[weekday] - market.base_day], "FX_SPOT"
                )
            )
        month_of_day = month_index(days) - months[0]
        daily = rates[: len(days)]
        if "FX_PERIOD_AVERAGE" in kinds:
            totals = np.bincount(month_of_day, weights=daily)
            average = np.round(totals / np.bincount(month_of_day), 6)
            parts.append(_series_frame(pair.series_id, ends, average, "FX_PERIOD_AVERAGE"))
        if "FX_PERIOD_END" in kinds:
            parts.append(
                _series_frame(
                    pair.series_id,
                    ends,
                    rates[np.minimum(ends, days[-1]) - market.base_day],
                    "FX_PERIOD_END",
                )
            )
    sheets["fx"] = pl.concat(parts)
    sheets["cpi"] = _series_frame(
        scenario.market.cpi.series_id, ends, market.cpi[: len(months)], "PRICE_INDEX"
    )
    return sheets


def _series_frame(series_id: str, days: np.ndarray, values: np.ndarray, kind: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "series_id": [series_id] * len(days),
            "date": date_series("date", days),
            "value": values,
            "kind": [kind] * len(days),
        }
    )
