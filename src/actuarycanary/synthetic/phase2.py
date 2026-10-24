"""The feeds added after version 1.0, built from the same simulated world as the first six.

Every stage draws from its own random streams (names that start with ``phase2``), so adding it
to a scenario moves nothing in the earlier feeds.

- reinsurance_treaties and reinsurance_transactions: ri_feeds (treaty table, ceded premium rows,
  treaty application per claim)
- recoveries: recoveries (the recovery events of the claim world)
- ledger: ledger (premiums, claims, reserves, expenses, reinsurance)
- interest_rates: rates (the scenario's inflation path)
- life_in_force, life_events, fund_flows: life (a life book with a known model, if enabled)
"""

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from actuarycanary.synthetic import ledger as ledger_module
from actuarycanary.synthetic import recoveries, ri_feeds, severity_truth
from actuarycanary.synthetic.claims import ClaimWorld
from actuarycanary.synthetic.days import month_index, to_day
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.life import build_life
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import (
    Policies,
    PremiumRows,
    first_valuation_month,
    simulation_years,
)
from actuarycanary.synthetic.rates import build_rates
from actuarycanary.synthetic.reinsurance import Reinsurance
from actuarycanary.synthetic.scenario import Scenario, SizeSpec

PHASE2_FEEDS = (
    "reinsurance_treaties",
    "reinsurance_transactions",
    "recoveries",
    "ledger",
    "interest_rates",
    "life_in_force",
    "life_events",
    "fund_flows",
)

# which later work item reads each truth file (listed in HANDOVER.md as well)
TRUTH_USERS = {
    "reinsurance_by_claim": "reinsurance item (CV09 allocation, MT21)",
    "reinsurance_by_treaty": "reinsurance item (RI03, RI04, RI05, M08)",
    "recoveries_truth": "recoveries and expenses item (RC03, RC04, M07)",
    "ledger_gaps": "ledger item (FN01, FN02, M10)",
    "ledger_differences": "ledger item (FN01, M10)",
    "interest_rates_truth": "uncertainty and discounting item (CV10, RS04)",
    "severity_truth": "severity and extremes item (MT17, MT18)",
    "severity_tail_truth": "severity and extremes item (MT18)",
    "life_contracts": "life experience item (MT20, LF01-LF04)",
    "life_mortality_truth": "life experience item (MT20, LF02)",
    "life_lapse_truth": "life experience item (MT20, LF01)",
    "life_expected_decrements": "life experience item (MT20, MT19)",
}


@dataclass
class Phase2Output:
    frames: dict[str, dict[str, pl.DataFrame]] = field(default_factory=dict)
    truth: dict[str, pl.DataFrame] = field(default_factory=dict)
    money: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)
    files: dict[str, pl.DataFrame] = field(default_factory=dict)  # path under the scenario folder


def build_phase2(
    scenario: Scenario,
    size: SizeSpec,
    size_name: str,
    market: Market,
    policies: Policies,
    premiums: PremiumRows,
    world: ClaimWorld,
    reinsurance: Reinsurance,
    valuations: pl.DataFrame,
    claim: np.ndarray,
    day: np.ndarray,
    expenses: pl.DataFrame,
    streams: Streams,
) -> Phase2Output:
    out = Phase2Output()
    cut_off = to_day(scenario.meta.valuation.last)
    first_month = first_valuation_month(scenario, size)
    last_month = int(month_index(cut_off))
    first_year, _ = simulation_years(scenario, size)
    window_start = to_day(_jan1(first_year))

    rates = build_rates(scenario, market, streams, first_month, last_month)
    out.frames["interest_rates"] = {"interest_rates": rates.feed.select(_RATE_COLUMNS)}
    out.truth["interest_rates_truth"] = rates.truth

    # reinsurance
    treaties = ri_feeds.treaty_table(scenario, market, window_start, cut_off)
    if treaties.height:
        state = world.state(claim, day)
        premium_rows = ri_feeds.premium_movements(scenario, policies, premiums)
        claim_rows = ri_feeds.claim_movements(
            scenario, world, reinsurance, valuations, claim, day, state
        )
        movements = ri_feeds.movements_table(premium_rows, claim_rows)
        out.frames["reinsurance_treaties"] = {"reinsurance_treaties": treaties}
        out.frames["reinsurance_transactions"] = {"reinsurance_transactions": movements}
        out.truth.update(
            ri_feeds.ceded_truth(scenario, world, reinsurance, movements, cut_off, window_start)
        )
        out.money.update(ri_feeds.MONEY_COLUMNS_RI)

    # recoveries
    feed, truth = recoveries.recovery_tables(scenario, world, streams)
    if feed.height:
        out.frames["recoveries"] = {"recoveries": feed}
        out.truth["recoveries_truth"] = truth
        out.money.update(recoveries.MONEY_COLUMNS_RECOVERIES)

    # ledger
    book = ledger_module.build_ledger(
        scenario,
        first_month,
        market,
        policies,
        premiums,
        world,
        valuations,
        claim,
        day,
        expenses,
        rates,
        streams,
    )
    out.frames["ledger"] = {"ledger": book.frame.select(_LEDGER_COLUMNS)}
    out.truth["ledger_gaps"] = book.gaps
    out.truth["ledger_differences"] = book.differences
    out.files["truth/ledger_mapping_profile.csv"] = book.profile
    out.money.update(ledger_module.MONEY_COLUMNS_LEDGER)

    # severity
    out.truth.update(severity_truth.severity_truth(scenario))
    out.money.update(severity_truth.MONEY_COLUMNS_SEVERITY)

    # life and pension
    if scenario.phase2.life_book.enabled:
        life = build_life(scenario, size, size_name, rates, streams)
        out.frames["life_in_force"] = {"life_in_force": life.in_force}
        out.frames["life_events"] = {"life_events": life.events}
        if life.flows.height:
            out.frames["fund_flows"] = {"fund_flows": life.flows}
        out.truth.update(life.truth)
        for name, table in life.reference.items():
            out.files[f"reference_tables/{name}.csv"] = table
    return out


def _jan1(year: int):
    from datetime import date

    return date(year, 1, 1)


_RATE_COLUMNS = [
    "curve_id",
    "date",
    "tenor_months",
    "rate",
    "rate_type",
    "compounding",
    "currency",
    "source",
]
_LEDGER_COLUMNS = [
    "entity",
    "account",
    "period",
    "closing_balance",
    "opening_balance",
    "debit",
    "credit",
    "currency",
    "account_name",
    "account_class",
    "segment",
]
