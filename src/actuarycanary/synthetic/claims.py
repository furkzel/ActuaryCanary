"""Claims: occurrence, reporting, settlement, payments, case reserves, reopenings, recoveries.

The whole life of every claim is simulated, including payments after the data cut-off. The
data files show only what was known at each valuation date; the truth keeps the rest.

Money mechanics: a claim has a cost X at base-date prices (in its own currency). A payment of
share w on day t is ``X * w * F(t)`` where F is the claims inflation index: the consumer
price index times superimposed inflation (for foreign currency: foreign inflation times
superimposed inflation, divided by the starting rate). A case reserve is the adjuster's
estimate of the remaining cost at *today's* prices, times a bias and a noise factor.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

from actuarycanary.synthetic.days import DAYS_PER_YEAR, month_index, to_day, years_since
from actuarycanary.synthetic.draws import Streams, draw
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import NO_DAY, Policies, simulation_years
from actuarycanary.synthetic.scenario import Line, Scenario, SizeSpec

STRIDE = 1 << 17  # larger than any day number used (about 2090)
END_OF_TIME = STRIDE - 1
MONTH_DAYS = 30.4375

OPEN, CLOSED, CLOSED_NIL, REOPENED, LITIGATED, NOT_REPORTED = 0, 1, 2, 3, 4, -1
STATUS_NAMES = {
    OPEN: "OPEN",
    CLOSED: "CLOSED",
    CLOSED_NIL: "CLOSED_NIL",
    REOPENED: "REOPENED",
    LITIGATED: "LITIGATED",
}

REGULAR, CATASTROPHE, SHOCK = 0, 1, 2


class Cumulative:
    """Running totals of event amounts per claim, queried at any day.

    Events must be sorted by (claim, day). ``at(claim, day)`` returns, for each value column,
    the sum of the claim's events on or before `day`.
    """

    def __init__(self, claim: np.ndarray, day: np.ndarray, *values: np.ndarray) -> None:
        self.key = claim.astype(np.int64) * STRIDE + day.astype(np.int64)
        self.totals = [np.concatenate([[0.0], np.cumsum(v, dtype=np.float64)]) for v in values]

    def at(self, claim: np.ndarray, day: np.ndarray) -> list[np.ndarray]:
        base = claim.astype(np.int64) * STRIDE
        hi = np.searchsorted(self.key, base + day, side="right")
        lo = np.searchsorted(self.key, base, side="left")
        return [t[hi] - t[lo] for t in self.totals]


@dataclass
class ClaimWorld:
    """Every simulated claim; one entry per claim in each ``c_*`` array."""

    scenario: Scenario
    market: Market
    policies: Policies
    # claim headers
    c_policy: np.ndarray
    c_line: np.ndarray
    c_entity: np.ndarray
    c_currency: np.ndarray
    c_occ: np.ndarray
    c_rep: np.ndarray
    c_e0: np.ndarray  # close of the first period of cover
    c_s1: np.ndarray  # reopening (NO_DAY when never reopened)
    c_e1: np.ndarray
    c_rho: np.ndarray  # share of the cost that comes after a reopening
    c_nil: np.ndarray
    c_litigated: np.ndarray
    c_kind: np.ndarray
    c_event: np.ndarray  # index into event_codes, -1 for none
    c_label: np.ndarray  # shock label or ""
    c_cost: np.ndarray  # X, cost at base-date prices in the claim's own currency (latent for nil)
    c_si: np.ndarray  # superimposed inflation of the claim's line
    c_infl_on: np.ndarray
    c_foreign_inflation: np.ndarray  # annual, 0 for the reporting currency
    c_fx_start: np.ndarray  # 1 for the reporting currency
    c_review_step: np.ndarray  # days between case reserve reviews
    c_cause: np.ndarray
    event_codes: list[str]
    event_dates: list[int]
    # payments: sorted by (claim, day)
    p_claim: np.ndarray
    p_day: np.ndarray
    p_w: np.ndarray
    p_amount: np.ndarray
    p_expense: np.ndarray
    # reviews: sorted by (claim, day)
    r_claim: np.ndarray
    r_day: np.ndarray
    r_estimate: np.ndarray
    # recoveries: sorted by (claim, day)
    v_claim: np.ndarray
    v_day: np.ndarray
    v_subrogation: np.ndarray
    v_salvage: np.ndarray

    def __post_init__(self) -> None:
        self._pay = Cumulative(self.p_claim, self.p_day, self.p_amount, self.p_w, self.p_expense)
        self._rev_key = self.r_claim.astype(np.int64) * STRIDE + self.r_day
        self._rec = Cumulative(self.v_claim, self.v_day, self.v_subrogation, self.v_salvage)
        self.has_reopen = self.c_s1 != NO_DAY
        self.last_event = np.maximum(self.c_e0, np.where(self.has_reopen, self.c_e1, 0))
        recovery_last = np.zeros(len(self), dtype=np.int64)
        np.maximum.at(recovery_last, self.v_claim, self.v_day)
        self.last_activity = np.maximum(self.last_event, recovery_last)

    def __len__(self) -> int:
        return len(self.c_occ)

    # --- inflation ---------------------------------------------------------------------

    def index_for(self, claim: np.ndarray, day: np.ndarray) -> np.ndarray:
        """Claims inflation index F of each claim at each day (aligned arrays)."""
        yrs = years_since(day, self.market.base_day)
        superimposed = (1.0 + self.c_si[claim]) ** yrs
        try_index = self.market.price_factor(day)
        foreign = (1.0 + self.c_foreign_inflation[claim]) ** yrs / self.c_fx_start[claim]
        reporting = self.c_fx_start[claim] == 1.0
        index = np.where(reporting, try_index, foreign) * superimposed
        return np.where(self.c_infl_on[claim], index, 1.0)

    # --- state at a day ----------------------------------------------------------------

    def state(self, claim: np.ndarray, day: np.ndarray) -> dict[str, np.ndarray]:
        """What is true of each claim at each day: cumulative amounts, reserve and status."""
        paid, weight, expense = self._pay.at(claim, day)
        subrogation, salvage = self._rec.at(claim, day)
        reported = day >= self.c_rep[claim]
        e0, s1, e1 = self.c_e0[claim], self.c_s1[claim], self.c_e1[claim]
        phase0 = reported & (day < e0)
        phase1 = (day >= s1) & (day < e1)
        is_open = phase0 | phase1

        # latest review on or before the day; its estimate falls as payments are made
        position = (
            np.searchsorted(self._rev_key, claim.astype(np.int64) * STRIDE + day, side="right") - 1
        )
        position = np.maximum(position, 0)
        has_review = is_open & (self.r_claim[position] == claim)
        review_day = np.where(has_review, self.r_day[position], 0)
        paid_at_review = self._pay.at(claim, review_day)[0]
        reserve = np.where(
            has_review, np.maximum(self.r_estimate[position] - (paid - paid_at_review), 0.0), 0.0
        )

        status = np.full(len(claim), CLOSED, dtype=np.int64)
        status[phase1] = REOPENED
        status[phase0] = np.where(self.c_litigated[claim][phase0], LITIGATED, OPEN)
        closed_nil = ~is_open & self.c_nil[claim] & reported
        status[closed_nil] = CLOSED_NIL
        status[~reported] = NOT_REPORTED
        return {
            "paid": paid,
            "reserve": reserve,
            "status": status,
            "subrogation": subrogation,
            "salvage": salvage,
            "expense": expense,
            "weight_paid": weight,
        }

    def ultimate(self) -> dict[str, np.ndarray]:
        """Final cumulative amounts of every claim (all payments, whenever made)."""
        claim = np.arange(len(self))
        return self.state(claim, np.full(len(self), END_OF_TIME, dtype=np.int64))


# --- construction ----------------------------------------------------------------------


def _bias_for(scenario: Scenario, line_name: str, line: Line, day: np.ndarray) -> np.ndarray:
    bias = np.full(len(day), line.case_reserve.initial_bias)
    changes = sorted(
        (c for c in scenario.reserving_practice_changes if c.line == line_name),
        key=lambda c: c.from_,
    )
    for change in changes:
        bias = np.where(day >= to_day(change.from_), change.initial_bias, bias)
    return bias


def _positive_days(values: np.ndarray, cap: int) -> np.ndarray:
    return np.minimum(np.maximum(np.rint(values), 1), cap).astype(np.int64)


def build_claims(
    scenario: Scenario, size: SizeSpec, market: Market, policies: Policies, streams: Streams
) -> ClaimWorld:
    first_year, last_year = simulation_years(scenario, size)
    window_lo = to_day(_first_day(first_year))
    window_hi = to_day(_first_day(last_year + 1))  # exclusive
    cap_days = scenario.meta.max_settlement_days
    event_codes: list[str] = []
    event_dates: list[int] = []
    blocks: list[dict[str, np.ndarray]] = []

    for name, line in scenario.lines.items():
        rng = streams.get("claims", name)
        mine = np.flatnonzero(policies.line == name)
        if len(mine) == 0:
            continue
        start, end, cancel = policies.start[mine], policies.end[mine], policies.cancel[mine]
        lo = np.maximum(start, window_lo)
        hi = np.minimum(np.minimum(end, cancel), window_hi)
        length = np.maximum(hi - lo, 0)

        # regular claims: Poisson process on exposure, thinned for a frequency trend
        freq = line.frequency.per_exposure_year
        trend = line.frequency.trend_per_year
        peak = (1.0 + trend) ** (
            np.maximum(years_since(hi, market.base_day), years_since(lo, market.base_day))
        )
        lam = freq * policies.units[mine] * length / DAYS_PER_YEAR * (peak if trend != 0 else 1.0)
        counts = rng.poisson(lam)
        pol = np.repeat(mine, counts)
        offset = np.repeat(lo, counts) + np.floor(
            rng.random(int(counts.sum())) * np.repeat(length, counts)
        ).astype(np.int64)
        if trend != 0:
            keep = rng.random(len(offset)) < (1.0 + trend) ** years_since(
                offset, market.base_day
            ) / np.repeat(peak, counts)
            pol, offset = pol[keep], offset[keep]
        parts = [
            (
                pol,
                offset,
                np.full(len(pol), REGULAR),
                np.full(len(pol), -1),
                np.full(len(pol), np.nan),
                np.full(len(pol), 1.0),
                np.full(len(pol), "", dtype=object),
            )
        ]

        reporting_currency = policies.currency[mine] == scenario.meta.reporting_currency
        last_cover_day = np.minimum(end, cancel)

        def in_force_try(
            day: int, mine=mine, start=start, last=last_cover_day, ok=reporting_currency
        ):
            """Policies of this line in force on `day`, in the reporting currency."""
            return mine[(start <= day) & (last > day) & ok]

        for event in line.catastrophe_events:
            day = to_day(event.date)
            if not window_lo <= day < window_hi:
                continue
            pool = in_force_try(day)
            n = min(len(pool), max(1, int(round(event.claims * size.portfolio_scale))))
            if n == 0:
                continue
            event_codes.append(event.event_code)
            event_dates.append(day)
            picked = rng.choice(pool, n, replace=False)
            parts.append(
                (
                    picked,
                    np.full(n, day),
                    np.full(n, CATASTROPHE),
                    np.full(n, len(event_codes) - 1),
                    np.full(n, np.nan),
                    np.full(n, event.severity_multiplier),
                    np.full(n, "", dtype=object),
                )
            )
        for shock in scenario.large_claims:
            day = to_day(shock.date)
            if shock.line != name or not window_lo <= day < window_hi:
                continue
            pool = in_force_try(day)
            if len(pool) == 0:
                continue
            picked = rng.choice(pool, 1)
            parts.append(
                (
                    picked,
                    np.array([day]),
                    np.array([SHOCK]),
                    np.array([-1]),
                    np.array([shock.cost_base]),
                    np.array([1.0]),
                    np.array([shock.label], dtype=object),
                )
            )

        pol = np.concatenate([p[0] for p in parts]).astype(np.int64)
        occ = np.concatenate([p[1] for p in parts]).astype(np.int64)
        kind = np.concatenate([p[2] for p in parts]).astype(np.int64)
        event = np.concatenate([p[3] for p in parts]).astype(np.int64)
        override = np.concatenate([p[4] for p in parts])
        multiplier = np.concatenate([p[5] for p in parts])
        label = np.concatenate([p[6] for p in parts])
        n = len(pol)
        currency = policies.currency[pol]
        fx0 = np.array([market.fx_start.get(c, 1.0) for c in currency]) if n else np.empty(0)
        foreign = (
            np.array([market.foreign_inflation.get(c, 0.0) for c in currency]) if n else np.empty(0)
        )

        # timeline
        rep = occ + np.maximum(np.floor(draw(line.reporting_delay_days, rng, n)), 0).astype(
            np.int64
        )
        lit = np.zeros(n, dtype=bool)
        settle_multiplier = np.ones(n)
        severity_multiplier = multiplier.copy()
        if line.litigation is not None:
            lit = rng.random(n) < line.litigation.probability
            settle_multiplier = np.where(lit, line.litigation.settlement_delay_multiplier, 1.0)
            severity_multiplier = severity_multiplier * np.where(
                lit, line.litigation.severity_multiplier, 1.0
            )
        e0 = rep + _positive_days(
            draw(line.settlement_delay_days, rng, n) * settle_multiplier, cap_days
        )
        nil = rng.random(n) < line.nil_close_probability
        reopen = (rng.random(n) < line.reopen_probability) & ~nil
        rho = np.where(reopen, rng.uniform(0.05, 0.4, n), 0.0)
        s1 = np.where(
            reopen, e0 + _positive_days(120 * np.exp(0.8 * rng.standard_normal(n)), 730), NO_DAY
        )
        e1 = np.where(
            reopen, s1 + _positive_days(45 * np.exp(0.6 * rng.standard_normal(n)), 365), NO_DAY
        )

        # cost at base-date prices, in the claim's currency
        infl_on = line.severity.body.dist != "fixed_share_of_sum_insured"
        if infl_on:
            body = draw(line.severity.body, rng, n)
            if line.severity.tail is not None:
                tail = line.severity.tail
                in_tail = rng.random(n) < tail.probability
                pareto = tail.threshold * (1.0 - rng.random(n)) ** (-1.0 / tail.alpha)
                body = np.where(in_tail, pareto, body)
            cost = body * severity_multiplier / fx0
            cost = np.where(np.isnan(override), cost, override / fx0)
        else:
            assert line.severity.body.share is not None
            cost = line.severity.body.share * policies.sum_insured[pol]  # nominal; no inflation
        world_si = line.severity.superimposed_inflation
        if infl_on and line.severity.capped_at_sum_insured and n:
            yrs = years_since(occ, market.base_day)
            index_at_loss = (
                np.where(fx0 == 1.0, market.price_factor(occ), (1.0 + foreign) ** yrs / fx0)
                * (1.0 + world_si) ** yrs
            )
            cost = np.where(
                kind == SHOCK,
                cost,
                np.minimum(cost, policies.sum_insured[pol] * policies.units[pol] / index_at_loss),
            )

        cause_names = list(line.causes)
        cause_p = np.array([line.causes[c] for c in cause_names]) / sum(line.causes.values())
        cause = rng.choice(np.array(cause_names, dtype=object), n, p=cause_p)
        cause[kind == CATASTROPHE] = "CATASTROPHE"
        blocks.append(
            dict(
                policy=pol,
                line=np.full(n, name, dtype=object),
                entity=policies.entity[pol],
                currency=currency,
                occ=occ,
                rep=rep,
                e0=e0,
                s1=s1,
                e1=e1,
                rho=rho,
                nil=nil,
                lit=lit,
                kind=kind,
                event=event,
                label=label,
                cost=cost,
                si=np.full(n, world_si),
                infl_on=np.full(n, infl_on),
                foreign=foreign,
                fx0=fx0,
                step=np.full(n, line.case_reserve.review_every_months * MONTH_DAYS),
                cause=cause,
            )
        )

    merged = {key: np.concatenate([b[key] for b in blocks]) for key in blocks[0]}
    order = np.lexsort(
        (merged["policy"], merged["occ"], merged["rep"])
    )  # claim numbers follow report dates
    merged = {key: value[order] for key, value in merged.items()}
    c = len(merged["occ"])

    pay_claim, pay_day, pay_w, pay_amount, pay_expense = [], [], [], [], []
    partial: dict[str, Any] = dict(
        scenario=scenario,
        market=market,
        policies=policies,
        c_policy=merged["policy"],
        c_line=merged["line"],
        c_entity=merged["entity"],
        c_currency=merged["currency"],
        c_occ=merged["occ"],
        c_rep=merged["rep"],
        c_e0=merged["e0"],
        c_s1=merged["s1"],
        c_e1=merged["e1"],
        c_rho=merged["rho"],
        c_nil=merged["nil"],
        c_litigated=merged["lit"],
        c_kind=merged["kind"],
        c_event=merged["event"],
        c_label=merged["label"],
        c_cost=merged["cost"],
        c_si=merged["si"],
        c_infl_on=merged["infl_on"],
        c_foreign_inflation=merged["foreign"],
        c_fx_start=merged["fx0"],
        c_review_step=merged["step"],
        c_cause=merged["cause"],
        event_codes=event_codes,
        event_dates=event_dates,
    )
    empty_f, empty_i = np.empty(0), np.empty(0, dtype=np.int64)
    skeleton = ClaimWorld(
        **partial,
        p_claim=empty_i,
        p_day=empty_i,
        p_w=empty_f,
        p_amount=empty_f,
        p_expense=empty_f,
        r_claim=empty_i,
        r_day=empty_i,
        r_estimate=empty_f,
        v_claim=empty_i,
        v_day=empty_i,
        v_subrogation=empty_f,
        v_salvage=empty_f,
    )

    # payments, line by line (each line has its own payment count, expense share and streams)
    for name, line in scenario.lines.items():
        ids = np.flatnonzero(merged["line"] == name)
        if len(ids) == 0:
            continue
        rng = streams.get("payments", name)
        counts = draw(line.payments.count, rng, len(ids)).astype(np.int64)
        counts = np.maximum(counts, 1)
        total = int(counts.sum())
        claim = np.repeat(ids, counts)
        slot = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
        is_last = slot == np.repeat(counts - 1, counts)
        rep, e0 = merged["rep"][claim], merged["e0"][claim]
        day = np.where(is_last, e0, rep + np.floor(rng.random(total) * (e0 - rep)).astype(np.int64))
        raw = rng.gamma(1.0, 1.0, total)
        sums = np.bincount(np.repeat(np.arange(len(ids)), counts), weights=raw)
        w = raw / np.repeat(sums, counts) * np.repeat(1.0 - merged["rho"][ids], counts)
        reopened = ids[merged["s1"][ids] != NO_DAY]
        claim = np.concatenate([claim, reopened])
        day = np.concatenate([day, merged["e1"][reopened]])
        w = np.concatenate([w, merged["rho"][reopened]])
        order = np.lexsort((day, claim))
        claim, day, w = claim[order], day[order], w[order]
        amount = np.round(merged["cost"][claim] * w * skeleton.index_for(claim, day), 2)
        amount = np.where(merged["nil"][claim], 0.0, amount)
        pay_claim.append(claim)
        pay_day.append(day)
        pay_w.append(w)
        pay_amount.append(amount)
        pay_expense.append(np.round(amount * line.allocated_expense_share, 2))
    p_claim, p_day, p_w, p_amount, p_expense = (
        np.concatenate(x) for x in (pay_claim, pay_day, pay_w, pay_amount, pay_expense)
    )
    order = np.lexsort((p_day, p_claim))
    p_claim, p_day, p_w, p_amount, p_expense = (
        p_claim[order],
        p_day[order],
        p_w[order],
        p_amount[order],
        p_expense[order],
    )

    # case reserve reviews: one unit per period of cover (the reopened period is a unit of its own)
    reopened = np.flatnonzero(merged["s1"] != NO_DAY)
    u_claim = np.concatenate([np.arange(c), reopened])
    u_start = np.concatenate([merged["rep"], merged["s1"][reopened]])
    u_end = np.concatenate([merged["e0"], merged["e1"][reopened]])
    u_weight_end = np.concatenate([1.0 - merged["rho"], np.ones(len(reopened))])
    step = merged["step"][u_claim]
    n_reviews = np.maximum(np.ceil((u_end - u_start) / step), 1).astype(np.int64)
    unit = np.repeat(np.arange(len(u_claim)), n_reviews)
    j = np.arange(len(unit)) - np.repeat(np.cumsum(n_reviews) - n_reviews, n_reviews)
    r_claim = u_claim[unit]
    r_day = u_start[unit] + np.floor(j * step[unit]).astype(np.int64)
    order = np.lexsort((r_day, r_claim))
    r_claim, r_day, unit = r_claim[order], r_day[order], unit[order]
    paid_weight = Cumulative(p_claim, p_day, p_w).at(r_claim, r_day)[0]
    remaining = np.maximum(u_weight_end[unit] - paid_weight, 0.0)
    estimate = merged["cost"][r_claim] * skeleton.index_for(r_claim, r_day) * remaining
    factor = np.ones(len(r_claim))
    for name, line in scenario.lines.items():
        at = np.flatnonzero(merged["line"][r_claim] == name)
        if len(at) == 0:
            continue
        sigma = line.case_reserve.noise_sigma
        noise = np.exp(
            sigma * streams.get("reserves", name).standard_normal(len(at)) - sigma**2 / 2
        )
        factor[at] = (1.0 + _bias_for(scenario, name, line, r_day[at])) * noise
    r_estimate = np.round(estimate * factor, 2)

    # recoveries: a share of what was paid, received some time after the last payment
    v_parts: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    paid_total = np.bincount(p_claim, weights=p_amount, minlength=c)
    last_pay = np.maximum(merged["e0"], np.where(merged["s1"] != NO_DAY, merged["e1"], 0))
    for name, line in scenario.lines.items():
        ids = np.flatnonzero(merged["line"] == name)
        for kind_name in ("subrogation", "salvage"):
            spec = getattr(line.recoveries, kind_name)
            if spec is None or len(ids) == 0:
                continue
            rng = streams.get("recoveries", name, kind_name)
            hit = ids[(rng.random(len(ids)) < spec.probability) & (paid_total[ids] > 0)]
            when = last_pay[hit] + _positive_days(draw(spec.delay_days, rng, len(hit)), 3650)
            amount = np.round(
                np.minimum(
                    paid_total[hit] * spec.recovered_share * rng.uniform(0.6, 1.4, len(hit)),
                    paid_total[hit],
                ),
                2,
            )
            zero = np.zeros(len(hit))
            v_parts.append(
                (
                    hit,
                    when,
                    amount if kind_name == "subrogation" else zero,
                    amount if kind_name == "salvage" else zero,
                )
            )
    if v_parts:
        v_claim, v_day, v_sub, v_salv = (np.concatenate([p[i] for p in v_parts]) for i in range(4))
        order = np.lexsort((v_day, v_claim))
        v_claim, v_day, v_sub, v_salv = v_claim[order], v_day[order], v_sub[order], v_salv[order]
    else:
        v_claim, v_day, v_sub, v_salv = empty_i, empty_i, empty_f, empty_f

    return ClaimWorld(
        **partial,
        p_claim=p_claim,
        p_day=p_day,
        p_w=p_w,
        p_amount=p_amount,
        p_expense=p_expense,
        r_claim=r_claim,
        r_day=r_day,
        r_estimate=r_estimate,
        v_claim=v_claim,
        v_day=v_day,
        v_subrogation=v_sub,
        v_salvage=v_salv,
    )


def _first_day(year: int):
    from datetime import date

    return date(year, 1, 1)


def month_positions(world: ClaimWorld, cut_off_day: int) -> tuple[np.ndarray, np.ndarray]:
    """First and last valuation month index (months since 1970-01) of each claim.

    A claim is valued from the month it is reported until the month of its last activity
    (closing, reopening or recovery), and at most until the cut-off month. A claim reported
    after the cut-off has first > last and no rows.
    """
    first = month_index(world.c_rep)
    last = np.minimum(month_index(world.last_activity), int(month_index(cut_off_day)))
    return first, last
