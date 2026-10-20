"""Policies, premium transactions and ceded premium."""

from dataclasses import dataclass, field

import numpy as np

from actuarycanary.synthetic.days import add_months, to_day
from actuarycanary.synthetic.draws import Streams, draw
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.scenario import Scenario, SizeSpec

NO_DAY = np.iinfo(np.int64).max  # "never": a cancellation that did not happen

# Premium transaction types, in the order they sort on one booking day.
PREMIUM_TYPES = (
    "WRITTEN",
    "COMMISSION",
    "ENDORSEMENT",
    "CANCELLATION",
    "REFUND",
    "CEDED_PREMIUM",
    "RI_COMMISSION",
)
WRITTEN_TYPES = ("WRITTEN", "ENDORSEMENT", "CANCELLATION", "REFUND")


@dataclass
class Policies:
    """One entry per policy; every array has the same length."""

    line: np.ndarray  # line name
    entity: np.ndarray
    product: np.ndarray
    partner: np.ndarray
    channel: np.ndarray
    currency: np.ndarray
    start: np.ndarray  # day numbers
    end: np.ndarray  # exclusive
    issue: np.ndarray
    cancel: np.ndarray  # NO_DAY when the policy ran to its end
    sum_insured: np.ndarray  # original currency, per risk unit
    units: np.ndarray
    premium: np.ndarray  # original currency, written at issue
    policy_id: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=object))

    def __len__(self) -> int:
        return len(self.start)


@dataclass
class PremiumRows:
    policy: np.ndarray  # index into Policies
    booking: np.ndarray
    effective: np.ndarray
    amount: np.ndarray
    type: np.ndarray  # one of PREMIUM_TYPES
    treaty: np.ndarray  # treaty id for ceded rows, "" otherwise

    def __len__(self) -> int:
        return len(self.policy)


def simulation_years(scenario: Scenario, size: SizeSpec) -> tuple[int, int]:
    """First and last accident year simulated."""
    if size.years is not None:
        return size.years
    return scenario.meta.accident_period.start.year, scenario.meta.accident_period.end.year


def first_valuation_month(scenario: Scenario, size: SizeSpec) -> int:
    """Month index (months since 1970-01) of the first valuation date that is simulated."""
    from actuarycanary.synthetic.days import month_index

    first_year, _ = simulation_years(scenario, size)
    return max(
        int(month_index(to_day(scenario.meta.valuation.first))),
        int(month_index(to_day(_jan1(first_year)))),
    )


def build_policies(
    scenario: Scenario, size: SizeSpec, market: Market, streams: Streams
) -> Policies:
    cut_off = to_day(scenario.meta.valuation.last)
    first_year, last_year = simulation_years(scenario, size)
    reference_year = scenario.meta.accident_period.start.year
    parts: list[dict[str, np.ndarray]] = []
    for name, line in scenario.lines.items():
        rng = streams.get("policies", name)
        term = line.portfolio.term_months
        back = -(-term // 12)  # cover that began before the first accident year still earns in it
        starts_list: list[np.ndarray] = []
        for year in range(first_year - back, last_year + 1):
            count = int(
                round(
                    line.portfolio.policies_first_year
                    * (1 + line.portfolio.growth_per_year) ** (year - reference_year)
                    * size.portfolio_scale
                )
            )
            lo, hi = to_day(_jan1(year)), to_day(_jan1(year + 1))
            starts_list.append(rng.integers(lo, hi, count))
        start = np.concatenate(starts_list)
        n = len(start)
        end = add_months(start, term)
        issue = start - np.where(rng.random(n) < 0.6, 0, rng.integers(1, 15, n))
        cancel = np.full(n, NO_DAY, dtype=np.int64)
        cancelled = rng.random(n) < line.portfolio.cancellation_probability
        span = np.maximum(end - start - 1, 1)
        cancel_day = start + 1 + np.floor(rng.random(n) * span).astype(np.int64)
        cancel[cancelled & (cancel_day <= cut_off)] = cancel_day[
            cancelled & (cancel_day <= cut_off)
        ]

        entity = rng.choice(np.array(line.entities, dtype=object), n)
        products = list(line.products)
        product = rng.choice(
            np.array(products, dtype=object), n, p=_weights(list(line.products.values()))
        )
        partner_ids = [p.id for p in scenario.partners]
        partner = rng.choice(
            np.array(partner_ids, dtype=object), n, p=_weights([p.share for p in scenario.partners])
        )
        channel_of = {p.id: p.channel for p in scenario.partners}
        channel = (
            np.array([channel_of[p] for p in partner], dtype=object)
            if n
            else np.empty(0, dtype=object)
        )

        currency = np.full(n, scenario.meta.reporting_currency, dtype=object)
        if line.portfolio.foreign_currency_share > 0:
            foreign = rng.random(n) < line.portfolio.foreign_currency_share
            codes = list(line.portfolio.foreign_currencies)
            currency[foreign] = rng.choice(
                np.array(codes, dtype=object),
                int(foreign.sum()),
                p=_weights([line.portfolio.foreign_currencies[c] for c in codes]),
            )

        # Sums insured move with prices: drawn at base-date prices, restated to the start date.
        sum_try = draw(line.portfolio.sum_insured, rng, n) * market.price_factor(start)
        sum_insured = sum_try.copy()
        for code in market.fx:
            mask = currency == code
            if mask.any():
                sum_insured[mask] = sum_try[mask] / market.fx_at(code, start[mask])
        units = draw(line.portfolio.exposure_units, rng, n) * size.exposure_multiplier.get(
            name, 1.0
        )
        if line.portfolio.exposure_units.dist != "fixed":
            units = np.maximum(1.0, np.rint(units))
        if line.premium.rate_on_sum_insured is not None:
            premium = line.premium.rate_on_sum_insured * sum_insured * units
        else:
            assert line.premium.per_policy is not None
            premium = line.premium.per_policy * market.price_factor(start) * units
        parts.append(
            dict(
                line=np.full(n, name, dtype=object),
                entity=entity,
                product=product,
                partner=partner,
                channel=channel,
                currency=currency,
                start=start,
                end=end,
                issue=issue,
                cancel=cancel,
                sum_insured=np.round(sum_insured, 2),
                units=units,
                premium=np.round(premium, 2),
            )
        )
    merged = {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}
    order = np.lexsort((merged["line"], merged["issue"]))  # ids follow issue order
    merged = {key: value[order] for key, value in merged.items()}
    policies = Policies(**merged)
    policies.policy_id = np.array([f"{i + 1:08d}" for i in range(len(policies))], dtype=object)
    return policies


def _jan1(year: int):
    from datetime import date

    return date(year, 1, 1)


def _weights(values: list[float]) -> np.ndarray:
    weights = np.asarray(values, dtype=np.float64)
    return weights / weights.sum()


def build_premiums(scenario: Scenario, policies: Policies, streams: Streams) -> PremiumRows:
    """Written, commission, endorsement, cancellation and refund rows, then the ceded rows."""
    cut_off = to_day(scenario.meta.valuation.last)
    n = len(policies)
    index = np.arange(n)
    chunks: list[PremiumRows] = []

    def add(rows_policy, booking, effective, amount, kind, treaty=""):
        keep = booking <= cut_off
        chunks.append(
            PremiumRows(
                rows_policy[keep],
                booking[keep],
                effective[keep],
                np.round(amount[keep], 2),
                np.full(int(keep.sum()), kind, dtype=object),
                np.full(int(keep.sum()), treaty, dtype=object),
            )
        )

    rate_commission = np.zeros(n)
    p_endorse = np.zeros(n)
    p_refund = np.zeros(n)
    for name, line in scenario.lines.items():
        mask = policies.line == name
        rate_commission[mask] = line.premium.commission_rate
        p_endorse[mask] = line.premium.endorsement_probability
        p_refund[mask] = line.premium.refund_probability

    rng = streams.get("premiums")
    premium = policies.premium
    add(index, policies.issue, policies.start, premium, "WRITTEN")
    add(index, policies.issue, policies.start, premium * rate_commission, "COMMISSION")

    endorsed = rng.random(n) < p_endorse
    eff = (
        policies.start
        + 1
        + np.floor(rng.random(n) * np.maximum(policies.end - policies.start - 1, 1)).astype(
            np.int64
        )
    )
    endorsed &= eff < policies.cancel
    sign = np.where(rng.random(n) < 0.6, 1.0, -1.0)
    delta = premium * rng.uniform(0.05, 0.25, n) * sign
    add(index[endorsed], eff[endorsed], eff[endorsed], delta[endorsed], "ENDORSEMENT")

    cancelled = policies.cancel != NO_DAY
    unexpired = (policies.end - policies.cancel) / np.maximum(policies.end - policies.start, 1)
    back = -premium * np.where(cancelled, unexpired, 0.0)
    add(
        index[cancelled],
        policies.cancel[cancelled],
        policies.cancel[cancelled],
        back[cancelled],
        "CANCELLATION",
    )
    add(
        index[cancelled],
        policies.cancel[cancelled],
        policies.cancel[cancelled],
        (back * rate_commission)[cancelled],
        "COMMISSION",
    )

    refunded = (rng.random(n) < p_refund) & ~cancelled
    when = (
        policies.start
        + 1
        + np.floor(rng.random(n) * np.maximum(policies.end - policies.start - 1, 1)).astype(
            np.int64
        )
    )
    refund = -premium * rng.uniform(0.02, 0.10, n)
    add(index[refunded], when[refunded], when[refunded], refund[refunded], "REFUND")

    gross = _concat(chunks)
    written = np.isin(gross.type, WRITTEN_TYPES)
    for treaty in scenario.reinsurance:
        covered = np.isin(policies.line[gross.policy], treaty.lines) & written
        if treaty.type == "QUOTA_SHARE":
            assert treaty.cession is not None
            factor = treaty.cession
        elif treaty.rate_on_gross_premium is not None:
            factor = treaty.rate_on_gross_premium
        else:
            continue
        covered &= gross.booking >= to_day(treaty.inception)
        ceded = factor * gross.amount[covered]
        parts = [
            (
                gross.policy[covered],
                gross.booking[covered],
                gross.effective[covered],
                ceded,
                "CEDED_PREMIUM",
            )
        ]
        if treaty.commission:
            parts.append(
                (
                    gross.policy[covered],
                    gross.booking[covered],
                    gross.effective[covered],
                    ceded * treaty.commission,
                    "RI_COMMISSION",
                )
            )
        for rows_policy, booking, effective, amount, kind in parts:
            chunks.append(
                PremiumRows(
                    rows_policy,
                    booking,
                    effective,
                    np.round(amount, 2),
                    np.full(len(amount), kind, dtype=object),
                    np.full(len(amount), treaty.treaty_id, dtype=object),
                )
            )
    rows = _concat(chunks)
    type_order = (
        np.array([PREMIUM_TYPES.index(t) for t in rows.type], dtype=np.int64)
        if len(rows)
        else np.empty(0, dtype=np.int64)
    )
    order = np.lexsort((rows.treaty, type_order, rows.policy, rows.booking))
    return PremiumRows(
        rows.policy[order],
        rows.booking[order],
        rows.effective[order],
        rows.amount[order],
        rows.type[order],
        rows.treaty[order],
    )


def _concat(chunks: list[PremiumRows]) -> PremiumRows:
    return PremiumRows(
        np.concatenate([c.policy for c in chunks]),
        np.concatenate([c.booking for c in chunks]),
        np.concatenate([c.effective for c in chunks]),
        np.concatenate([c.amount for c in chunks]),
        np.concatenate([c.type for c in chunks]),
        np.concatenate([c.treaty for c in chunks]),
    )
