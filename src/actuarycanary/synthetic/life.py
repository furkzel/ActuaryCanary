"""A life and pension book with a known mortality and lapse model.

Contracts of a few products enter over the years (a share of them before the first valuation, so
that durations differ). Between two policy anniversaries the force of mortality and of lapse is
constant, so the exit time of a contract is drawn exactly:

    mu(x) = multiplier(product) * factor(sex) * (a + b * c ** x)
    x = entry age + whole policy years
    lapse hazard in policy year k = -ln(1 - rate_k * lapse_multiplier)

Age moves on policy anniversaries, as CV11 reads it, so a study that follows CV11 recovers the
model exactly. The truth files hold the model, every contract's timeline and the exposure and the
true expected decrements by calendar year, product, age and policy year. The reference tables
(mortality and lapse) are the model before the product multipliers.

Funds (savings and pension products) grow at the one-year rate of the reporting-currency curve
less a spread, receive contributions, pay fees and withdrawals, and are paid out on exit.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.synthetic.days import (
    add_months,
    month_end,
    month_index,
    month_start,
    to_day,
    year_of,
)
from actuarycanary.synthetic.draws import Streams, draw
from actuarycanary.synthetic.feeds import date_series, id_text
from actuarycanary.synthetic.portfolio import simulation_years
from actuarycanary.synthetic.rates import Rates, one_year_rate
from actuarycanary.synthetic.scenario import LifeBook, Scenario, SizeSpec

BIG = np.int64(1) << 40  # "never"
DEATH, LAPSE, TRANSFER_OUT, MATURITY, CENSORED = 0, 1, 2, 3, 4
PERIOD_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "HALF_YEARLY": 6, "YEARLY": 12, "SINGLE": 0}
STATUS_OF = {
    DEATH: "DEATH_CLAIM",
    LAPSE: "LAPSED",
    TRANSFER_OUT: "TRANSFERRED_OUT",
    MATURITY: "MATURED",
    CENSORED: "IN_FORCE",
}
EVENT_OF = {DEATH: "DEATH", LAPSE: "LAPSE", TRANSFER_OUT: "TRANSFER_OUT", MATURITY: "MATURITY"}
SEX_NAMES = np.array(["FEMALE", "MALE"], dtype=object)
MAX_YEARS = 40


def gompertz_makeham(book: LifeBook, age: np.ndarray) -> np.ndarray:
    m = book.mortality
    return m.a + m.b * m.c ** np.asarray(age, dtype=np.float64)


def _jan1(year: int) -> date:
    return date(year, 1, 1)


def _dec31(year: int) -> date:
    return date(year, 12, 31)


def jan1_days(years: np.ndarray) -> np.ndarray:
    """Day number of 1 January of each year."""
    return (
        (np.asarray(years) - 1970).astype("datetime64[Y]").astype("datetime64[D]").astype(np.int64)
    )


def whole_years(entry: np.ndarray, day: np.ndarray) -> np.ndarray:
    """Whole policy years completed at `day` (anniversaries as `add_months` puts them)."""
    guess = year_of(day) - year_of(entry)
    return guess - (shift_years(entry, guess) > day).astype(np.int64)


def shift_years(days: np.ndarray, years: np.ndarray) -> np.ndarray:
    """The same day of the month `years` later (element by element), as `add_months` moves it."""
    stamp = days.astype("datetime64[D]")
    month = stamp.astype("datetime64[M]")
    day_of_month = (stamp - month.astype("datetime64[D]")).astype(np.int64)
    target = month + (12 * np.asarray(years)).astype("timedelta64[M]")
    length = (target + np.timedelta64(1, "M")).astype("datetime64[D]") - target.astype(
        "datetime64[D]"
    )
    day = np.minimum(day_of_month, length.astype(np.int64) - 1)
    return target.astype("datetime64[D]").astype(np.int64) + day


@dataclass
class Contracts:
    """Every simulated contract, one entry per contract."""

    product: np.ndarray
    entry: np.ndarray  # day
    entry_age: np.ndarray
    sex: np.ndarray  # 0 female, 1 male
    sum_assured: np.ndarray
    premium: np.ndarray  # annual premium (risk products)
    contribution: np.ndarray  # annual member contribution (fund products)
    transfer_in: np.ndarray  # amount transferred in at entry
    employer: np.ndarray  # bool
    maturity: np.ndarray  # day of the end of the term, BIG without a term

    def __len__(self) -> int:
        return len(self.entry)


@dataclass
class Timelines:
    exit1: np.ndarray
    cause1: np.ndarray
    reinstated: np.ndarray  # bool
    restart: np.ndarray  # day of the reinstatement, BIG otherwise
    exit2: np.ndarray
    cause2: np.ndarray

    @property
    def final_exit(self) -> np.ndarray:
        return np.where(self.reinstated, self.exit2, self.exit1)

    @property
    def final_cause(self) -> np.ndarray:
        return np.where(self.reinstated, self.cause2, self.cause1)


# --- contracts -------------------------------------------------------------------------


def build_contracts(
    scenario: Scenario, size: SizeSpec, size_name: str, streams: Streams
) -> Contracts:
    book = scenario.phase2.life_book
    first_year, last_year = simulation_years(scenario, size)
    scale = size.portfolio_scale * book.count_scale_by_size.get(size_name, 1.0)
    parts: list[Contracts] = []
    for index, product in enumerate(book.products):
        rng = streams.get("phase2", "life", "contracts", product.key)
        for year in range(first_year - book.opening_years, last_year + 1):
            count = product.contracts_first_year * scale
            count *= (1.0 + product.growth_per_year) ** (year - first_year)
            if year < first_year:
                count *= book.opening_share
            n = int(rng.poisson(count)) if count > 0 else 0
            if n == 0:
                continue
            lo, hi = to_day(_jan1(year)), to_day(_jan1(year + 1))
            entry = lo + np.floor(rng.random(n) * (hi - lo)).astype(np.int64)
            age = np.clip(
                np.rint(rng.normal(product.entry_age_mean, product.entry_age_sd, n)),
                product.entry_age_min,
                product.entry_age_max,
            ).astype(np.int64)
            sex = (rng.random(n) < 0.5).astype(np.int64)
            sum_assured = (
                draw(product.sum_assured, rng, n)
                if product.sum_assured is not None
                else np.zeros(n)
            )
            loading = np.maximum(1.0 + 0.03 * (age - 35.0), 0.3)
            premium = np.round(sum_assured * product.premium_rate * loading, 2)
            contribution = (
                np.round(draw(product.annual_contribution, rng, n), 2)
                if product.annual_contribution is not None
                else np.zeros(n)
            )
            transfer = np.where(
                rng.random(n) < product.transfer_in_share,
                np.round(contribution * rng.uniform(1.0, 6.0, n), 2),
                0.0,
            )
            employer = rng.random(n) < product.employer_contribution_share
            maturity = (
                add_months(entry, 12 * product.term_years)
                if product.term_years is not None
                else np.full(n, BIG)
            )
            parts.append(
                Contracts(
                    np.full(n, index),
                    entry,
                    age,
                    sex,
                    np.round(sum_assured, 2),
                    premium,
                    contribution,
                    transfer,
                    employer,
                    maturity.astype(np.int64),
                )
            )
    if not parts:
        raise ValueError("the life book has no contracts at this size")
    return Contracts(
        *(np.concatenate([getattr(p, f) for p in parts]) for f in Contracts.__dataclass_fields__)
    )


# --- hazards and exits -----------------------------------------------------------------------


def _tables(book: LifeBook) -> tuple[np.ndarray, np.ndarray]:
    """Lapse rates (reference and true) by product and policy year, padded to MAX_YEARS."""
    reference = np.zeros((len(book.products), MAX_YEARS))
    true = np.zeros_like(reference)
    for i, p in enumerate(book.products):
        rates = np.array(p.lapse_by_policy_year, dtype=np.float64)
        padded = np.concatenate([rates, np.full(MAX_YEARS - len(rates), rates[-1])])[:MAX_YEARS]
        reference[i] = padded
        true[i] = np.minimum(padded * p.lapse_multiplier, 0.95)
    return reference, true


def _simulate(
    book: LifeBook,
    contracts: Contracts,
    index: np.ndarray,
    start: np.ndarray,
    horizon: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Exit day and cause of the contracts `index`, each in force from `start` on."""
    n = len(index)
    entry = contracts.entry[index]
    product = contracts.product[index]
    _, true_lapse = _tables(book)
    multiplier = np.array([p.mortality_multiplier for p in book.products])[product]
    sex_factor = np.where(
        contracts.sex[index] == 1, book.mortality.male_factor, book.mortality.female_factor
    )
    transfer_rate = np.array([p.transfer_out_rate for p in book.products])[product]
    maturity = contracts.maturity[index]
    age0 = contracts.entry_age[index]
    exit_day = np.full(n, BIG, dtype=np.int64)
    cause = np.full(n, CENSORED, dtype=np.int64)
    alive = np.ones(n, dtype=bool)
    shock = rng.exponential(1.0, n)
    for k in range(MAX_YEARS):
        lo_year = add_months(entry, 12 * k)
        if not alive.any() or (lo_year > horizon).all():
            break
        hi_year = add_months(entry, 12 * (k + 1))
        seg_lo = np.maximum(start, lo_year)
        seg_hi = np.minimum(np.minimum(hi_year, maturity), horizon + 1)
        span = seg_hi - seg_lo
        live = alive & (span > 0)
        mu = multiplier * sex_factor * gompertz_makeham(book, age0 + k)
        hazard_lapse = -np.log1p(-true_lapse[product, k])
        total = mu + hazard_lapse + transfer_rate
        cumulative = total * span / 365.25
        hit = live & (shock < cumulative)
        if hit.any():
            safe = np.where(total > 0, total, 1.0)
            day = seg_lo + np.floor(shock / safe * 365.25).astype(np.int64)
            exit_day[hit] = day[hit]
            pick = rng.random(n) * total
            kind = np.where(
                pick < mu, DEATH, np.where(pick < mu + hazard_lapse, LAPSE, TRANSFER_OUT)
            )
            cause[hit] = kind[hit]
            alive[hit] = False
        still = live & ~hit
        shock = np.where(still, shock - cumulative, shock)
        # the term ends inside this policy year
        ended = still & (maturity <= hi_year) & (maturity <= horizon) & (maturity > lo_year)
        exit_day[ended] = maturity[ended]
        cause[ended] = MATURITY
        alive[ended] = False
    return exit_day, cause


def simulate_timelines(
    book: LifeBook, contracts: Contracts, cut_off: int, window_start: int, streams: Streams
) -> Timelines:
    n = len(contracts)
    exit1, cause1 = _simulate(
        book,
        contracts,
        np.arange(n),
        contracts.entry,
        cut_off,
        streams.get("phase2", "life", "exits"),
    )
    rng = streams.get("phase2", "life", "reinstatement")
    probability = np.array([p.reinstatement_probability for p in book.products])[contracts.product]
    wish = (cause1 == LAPSE) & (exit1 >= window_start) & (rng.random(n) < probability)
    restart = np.where(wish, exit1 + rng.integers(20, 81, n), BIG)
    wish &= (restart <= cut_off) & (restart < contracts.maturity)
    restart = np.where(wish, restart, BIG).astype(np.int64)
    exit2 = np.full(n, BIG, dtype=np.int64)
    cause2 = np.full(n, CENSORED, dtype=np.int64)
    again = np.flatnonzero(wish)
    if len(again):
        e2, c2 = _simulate(
            book, contracts, again, restart[again], cut_off, streams.get("phase2", "life", "exits2")
        )
        exit2[again], cause2[again] = e2, c2
    return Timelines(exit1, cause1, wish, restart, exit2, cause2)


# --- funds and flows -----------------------------------------------------------------------


@dataclass
class FundResult:
    flows: pl.DataFrame  # contract index, day, flow type, amount, fund code
    value_at: dict[int, np.ndarray]  # valuation day -> fund value of every contract
    payout: np.ndarray  # fund value paid out on the final exit
    withdrawals: pl.DataFrame  # contract index, day, amount


_FLOW_SCHEMA = {
    "contract": pl.Int64,
    "day": pl.Int64,
    "flow_type": pl.String,
    "amount": pl.Float64,
    "fund_code": pl.String,
}


def simulate_funds(
    book: LifeBook,
    contracts: Contracts,
    timelines: Timelines,
    rates: Rates,
    scenario: Scenario,
    valuation_days: list[int],
    streams: Streams,
) -> FundResult:
    n = len(contracts)
    products = book.products
    fund_idx = np.flatnonzero(np.array([p.has_fund for p in products])[contracts.product])
    value_at = {d: np.zeros(n) for d in valuation_days}
    payout = np.zeros(n)
    no_flows = pl.DataFrame(schema=_FLOW_SCHEMA)
    no_draws = pl.DataFrame(schema={"contract": pl.Int64, "day": pl.Int64, "amount": pl.Float64})
    if len(fund_idx) == 0:
        return FundResult(no_flows, value_at, payout, no_draws)
    rng = streams.get("phase2", "life", "funds")
    horizon = max(valuation_days)
    product = contracts.product[fund_idx]
    entry = contracts.entry[fund_idx]
    exit_day = timelines.final_exit[fund_idx]
    final_cause = timelines.final_cause[fund_idx]
    period = np.array([PERIOD_MONTHS[p.premium_frequency] for p in products])[product]
    per_amount = np.where(
        period > 0, contracts.contribution[fund_idx] * np.maximum(period, 1) / 12.0, 0.0
    )
    single = np.where(period == 0, contracts.contribution[fund_idx], 0.0)
    state_rate = np.array([p.state_contribution_rate for p in products])[product]
    fee_rate = np.array([p.fund_fee_rate for p in products])[product]
    withdraw_rate = np.array([p.partial_withdrawal_rate for p in products])[product]
    switch_p = book.switch_probability_per_year / 12.0
    employer = contracts.employer[fund_idx]
    transfer_in = contracts.transfer_in[fund_idx]
    entry_month = month_index(entry)
    entry_dom = entry - month_start(entry_month)
    exit_month = month_index(np.minimum(exit_day, horizon + 400))
    first_month = int(entry_month.min())
    last_month = int(month_index(horizon))
    fund = np.zeros(len(fund_idx))
    rows: list[pl.DataFrame] = []
    withdrawals: list[pl.DataFrame] = []
    valuation_months = {int(month_index(d)): d for d in valuation_days}
    names = np.array(book.funds, dtype=object)
    reporting = scenario.meta.reporting_currency

    def emit(local: np.ndarray, day: np.ndarray, kind: str, amount: np.ndarray, code=None) -> None:
        if len(local) == 0:
            return
        rows.append(
            pl.DataFrame(
                {
                    "contract": fund_idx[local],
                    "day": day,
                    "flow_type": [kind] * len(local),
                    "amount": np.round(amount, 2),
                    "fund_code": [None] * len(local) if code is None else code.tolist(),
                },
                schema=_FLOW_SCHEMA,
            )
        )

    for month in range(first_month, last_month + 1):
        rate = float(one_year_rate(rates, reporting, np.array([month]))[0])
        growth = max(rate - book.fund_return_spread, 0.0) / 12.0
        m_start, m_end = int(month_start(month)), int(month_end(month))
        started = entry_month <= month
        running = started & (exit_day >= m_start)
        fund = np.where(running, fund * (1.0 + growth), fund)
        day = np.minimum(
            m_start + entry_dom, m_end
        )  # the day of the month the contract's dates fall on
        live = running & (day >= entry) & (day < exit_day)
        elapsed = month - entry_month
        # transfer in at entry
        entering = running & (entry_month == month) & (transfer_in > 0)
        if entering.any():
            local = np.flatnonzero(entering)
            emit(local, entry[local], "TRANSFER_IN", transfer_in[local])
            fund[local] += transfer_in[local]
        # member, state and employer contributions
        regular = (period > 0) & started & (elapsed % np.maximum(period, 1) == 0)
        member = np.where(live & regular, per_amount, 0.0) + np.where(
            live & (period == 0) & (entry_month == month), single, 0.0
        )
        paying = np.flatnonzero(member > 0)
        if len(paying):
            emit(paying, day[paying], "CONTRIBUTION", member[paying])
            state = np.round(member * state_rate, 2)
            with_state = np.flatnonzero(state > 0)
            emit(with_state, day[with_state], "STATE_CONTRIBUTION", state[with_state])
            boss = np.where(employer, np.round(member * 0.5, 2), 0.0)
            with_boss = np.flatnonzero(boss > 0)
            emit(with_boss, day[with_boss], "EMPLOYER_CONTRIBUTION", boss[with_boss])
            fund += np.round(member, 2) + state + boss
        # annual fee on the anniversary
        fee = np.where(
            live & (elapsed > 0) & (elapsed % 12 == 0), np.round(fund * fee_rate, 2), 0.0
        )
        charged = np.flatnonzero(fee > 0)
        if len(charged):
            emit(charged, day[charged], "FEE", fee[charged])
            fund -= fee
        # partial withdrawals
        wants = live & (rng.random(len(fund_idx)) < withdraw_rate / 12.0) & (fund > 0)
        if wants.any():
            local = np.flatnonzero(wants)
            when = m_start + np.floor(rng.random(len(local)) * (m_end - m_start + 1)).astype(
                np.int64
            )
            ok = (when >= entry[local]) & (when < exit_day[local])
            local, when = local[ok], when[ok]
            amount = np.round(fund[local] * rng.uniform(0.05, 0.25, len(local)), 2)
            emit(local, when, "BENEFIT_PAYMENT", amount)
            withdrawals.append(
                pl.DataFrame(
                    {"contract": fund_idx[local], "day": when, "amount": amount},
                    schema=no_draws.schema,
                )
            )
            fund[local] -= amount
        # a switch between two funds: out of one, into the other, same day
        if len(names) > 1:
            switching = live & (rng.random(len(fund_idx)) < switch_p) & (fund > 0)
            if switching.any():
                local = np.flatnonzero(switching)
                out_code = rng.integers(len(names), size=len(local))
                in_code = (out_code + 1 + rng.integers(len(names) - 1, size=len(local))) % len(
                    names
                )
                amount = np.round(fund[local] * rng.uniform(0.1, 0.5, len(local)), 2)
                emit(local, day[local], "FUND_SWITCH", -amount, names[out_code])
                emit(local, day[local], "FUND_SWITCH", amount, names[in_code])
        # the fund is paid out in the month of the exit
        leaving = running & (exit_month == month) & (final_cause != CENSORED)
        if leaving.any():
            local = np.flatnonzero(leaving)
            amount = np.round(fund[local], 2)
            payout[fund_idx[local]] = amount
            moves = final_cause[local] == TRANSFER_OUT
            paid = amount > 0
            emit(
                local[moves & paid],
                exit_day[local][moves & paid],
                "TRANSFER_OUT",
                amount[moves & paid],
            )
            emit(
                local[~moves & paid],
                exit_day[local][~moves & paid],
                "BENEFIT_PAYMENT",
                amount[~moves & paid],
            )
            fund[local] = 0.0
        if month in valuation_months:
            value_at[valuation_months[month]][fund_idx] = np.round(fund, 2)
    flows = pl.concat(rows) if rows else no_flows
    drawn = pl.concat(withdrawals) if withdrawals else no_draws
    return FundResult(flows, value_at, payout, drawn)


# --- feeds -------------------------------------------------------------------------------


@dataclass
class LifeResult:
    in_force: pl.DataFrame
    events: pl.DataFrame
    flows: pl.DataFrame
    truth: dict[str, pl.DataFrame]
    reference: dict[str, pl.DataFrame]


def _entity_of(scenario: Scenario, segment: str) -> str | None:
    for wanted in (segment, "LIFE"):
        for e in scenario.entities:
            if wanted in e.segments:
                return e.id
    return None


def _band(age: np.ndarray, width: int) -> list[str]:
    if width <= 1:
        return [str(int(a)) for a in age]
    low = (age // width) * width
    return [f"{int(a)}-{int(a) + width - 1}" for a in low]


def build_life(
    scenario: Scenario,
    size: SizeSpec,
    size_name: str,
    rates: Rates,
    streams: Streams,
) -> LifeResult:
    book = scenario.phase2.life_book
    first_year, last_year = simulation_years(scenario, size)
    cut_off = to_day(scenario.meta.valuation.last)
    window_start = to_day(_jan1(first_year))
    valuation_days = [
        d for d in (to_day(_dec31(y)) for y in range(first_year, last_year + 1)) if d <= cut_off
    ]
    contracts = build_contracts(scenario, size, size_name, streams)
    timelines = simulate_timelines(book, contracts, cut_off, window_start, streams)
    # a contract that left before the first year is not in the data at all
    seen = timelines.final_exit >= window_start
    funds = simulate_funds(book, contracts, timelines, rates, scenario, valuation_days, streams)
    n = len(contracts)
    ids = np.array(id_text("L", np.arange(1, n + 1), 8), dtype=object)
    lag = np.maximum(
        np.rint(draw(book.mortality.reporting_lag_days, streams.get("phase2", "life", "lag"), n)), 0
    ).astype(np.int64)
    report1 = np.where(timelines.cause1 == DEATH, timelines.exit1 + lag, BIG)
    report2 = np.where(
        timelines.reinstated & (timelines.cause2 == DEATH), timelines.exit2 + lag, BIG
    )
    in_force = _in_force_rows(
        scenario, book, contracts, timelines, funds, ids, valuation_days, seen, report1, report2
    )
    events = _event_rows(
        scenario,
        book,
        contracts,
        timelines,
        funds,
        ids,
        window_start,
        cut_off,
        seen,
        report1,
        report2,
    )
    flows = _flow_rows(scenario, funds, ids, window_start, cut_off, seen)
    truth = _truth(
        scenario, book, contracts, timelines, ids, seen, window_start, cut_off, report1, report2
    )
    return LifeResult(in_force, events, flows, truth, _reference_tables(book))


def _known(exit_day: np.ndarray, cause: np.ndarray, report: np.ndarray) -> np.ndarray:
    """The day an exit is known: a death when it is reported, the rest when it happens."""
    return np.where(cause == DEATH, report, exit_day)


def _in_force_rows(
    scenario: Scenario,
    book: LifeBook,
    contracts: Contracts,
    timelines: Timelines,
    funds: FundResult,
    ids: np.ndarray,
    valuation_days: list[int],
    seen: np.ndarray,
    report1: np.ndarray,
    report2: np.ndarray,
) -> pl.DataFrame:
    products = book.products
    known1 = _known(timelines.exit1, timelines.cause1, report1)
    known2 = np.where(timelines.reinstated, _known(timelines.exit2, timelines.cause2, report2), BIG)
    final_known = np.where(timelines.reinstated, known2, known1)
    label = np.array([STATUS_OF[c] for c in range(5)], dtype=object)
    surrender = np.array([p.lapse_decrement == "SURRENDER" for p in products])[contracts.product]
    status1 = np.where(
        (timelines.cause1 == LAPSE) & surrender, "SURRENDERED", label[timelines.cause1]
    )
    status2 = np.where(
        (timelines.cause2 == LAPSE) & surrender, "SURRENDERED", label[timelines.cause2]
    )
    p_key = np.array([p.key for p in products], dtype=object)[contracts.product]
    p_line = np.array([p.line for p in products], dtype=object)[contracts.product]
    p_segment = np.array([p.segment for p in products], dtype=object)[contracts.product]
    p_type = np.array([p.policy_type for p in products], dtype=object)[contracts.product]
    p_channel = np.array([p.channel for p in products], dtype=object)[contracts.product]
    p_frequency = np.array([p.premium_frequency for p in products], dtype=object)[contracts.product]
    p_term = np.array([np.nan if p.term_years is None else float(p.term_years) for p in products])[
        contracts.product
    ]
    p_width = np.array([p.age_band_width for p in products])[contracts.product]
    p_fund = np.array([p.has_fund for p in products])[contracts.product]
    entity = {s: _entity_of(scenario, s) for s in ("LIFE", "PENSION")}
    pieces: list[pl.DataFrame] = []
    for j, v in enumerate(valuation_days):
        previous = valuation_days[j - 1] if j else -BIG
        # a row at every valuation date from the first one until the exit is known
        rows = seen & (contracts.entry <= v) & (final_known > previous)
        idx = np.flatnonzero(rows)
        if len(idx) == 0:
            continue
        status = np.where(v >= known1[idx], status1[idx], "IN_FORCE")
        back = timelines.reinstated[idx] & (v >= timelines.restart[idx])
        status = np.where(back, "IN_FORCE", status)
        status = np.where(timelines.reinstated[idx] & (v >= known2[idx]), status2[idx], status)
        running = status == "IN_FORCE"
        age = contracts.entry_age[idx] + whole_years(contracts.entry[idx], np.full(len(idx), v))
        band = np.empty(len(idx), dtype=object)
        for w in np.unique(p_width[idx]):
            sel = p_width[idx] == w
            band[sel] = _band(age[sel], int(w))
        fund_value = np.where(p_fund[idx] & running, funds.value_at[v][idx], np.nan)
        sum_assured = np.where(contracts.sum_assured[idx] > 0, contracts.sum_assured[idx], np.nan)
        premium = np.where(
            contracts.premium[idx] > 0, contracts.premium[idx], contracts.contribution[idx]
        )
        pieces.append(
            pl.DataFrame(
                {
                    "contract_id": ids[idx].tolist(),
                    "valuation_date": date_series("valuation_date", np.full(len(idx), v)),
                    "product": p_key[idx].tolist(),
                    "entry_date": date_series("entry_date", contracts.entry[idx]),
                    "age_band": band.tolist(),
                    "status": status.tolist(),
                    "segment": p_segment[idx].tolist(),
                    "line": p_line[idx].tolist(),
                    "entity": [entity[s] for s in p_segment[idx]],
                    "policy_type": p_type[idx].tolist(),
                    "channel": p_channel[idx].tolist(),
                    "term_years": pl.Series(p_term[idx]).fill_nan(None),
                    "sum_assured": pl.Series(sum_assured).fill_nan(None),
                    "fund_value": pl.Series(fund_value).fill_nan(None),
                    "annual_premium": np.where(running, premium, 0.0),
                    "premium_frequency": p_frequency[idx].tolist(),
                    "currency": [scenario.meta.reporting_currency] * len(idx),
                    "sex": SEX_NAMES[contracts.sex[idx]].tolist(),
                }
            )
        )
    return pl.concat(pieces).sort(["valuation_date", "contract_id"])


def _event_rows(
    scenario: Scenario,
    book: LifeBook,
    contracts: Contracts,
    timelines: Timelines,
    funds: FundResult,
    ids: np.ndarray,
    window_start: int,
    cut_off: int,
    seen: np.ndarray,
    report1: np.ndarray,
    report2: np.ndarray,
) -> pl.DataFrame:
    products = book.products
    has_fund = np.array([p.has_fund for p in products])[contracts.product]
    surrender = np.array([p.lapse_decrement == "SURRENDER" for p in products])[contracts.product]
    death_benefit = np.where(
        has_fund, np.maximum(contracts.sum_assured, funds.payout), contracts.sum_assured
    )
    parts: list[dict[str, np.ndarray]] = []

    def terminal(
        exit_day: np.ndarray, cause: np.ndarray, report: np.ndarray, valid: np.ndarray
    ) -> None:
        for code, name in EVENT_OF.items():
            hit = (
                valid & seen & (cause == code) & (exit_day >= window_start) & (exit_day <= cut_off)
            )
            if code == DEATH:
                hit &= report <= cut_off
            idx = np.flatnonzero(hit)
            if len(idx) == 0:
                continue
            kind = np.full(len(idx), name, dtype=object)
            amount = np.full(len(idx), np.nan)
            if code == DEATH:
                amount = death_benefit[idx]
            elif code in (TRANSFER_OUT, MATURITY):
                amount = np.where(has_fund[idx], funds.payout[idx], np.nan)
            else:
                kind = np.where(surrender[idx], "SURRENDER", "LAPSE")
                amount = np.where(has_fund[idx] & surrender[idx], funds.payout[idx], np.nan)
            parts.append(
                {
                    "contract": idx,
                    "event_date": exit_day[idx],
                    "event_type": kind,
                    "report_date": report[idx] if code == DEATH else np.full(len(idx), -1),
                    "amount": amount,
                }
            )

    terminal(timelines.exit1, timelines.cause1, report1, np.ones(len(contracts), dtype=bool))
    terminal(timelines.exit2, timelines.cause2, report2, timelines.reinstated)
    again = np.flatnonzero(timelines.reinstated & seen)
    parts.append(_plain(again, timelines.restart[again], "REINSTATEMENT"))
    came = np.flatnonzero(seen & (contracts.transfer_in > 0) & (contracts.entry >= window_start))
    parts.append(_plain(came, contracts.entry[came], "TRANSFER_IN", contracts.transfer_in[came]))
    w = funds.withdrawals.filter((pl.col("day") >= window_start) & (pl.col("day") <= cut_off))
    parts.append(
        _plain(
            w["contract"].to_numpy(),
            w["day"].to_numpy(),
            "PARTIAL_WITHDRAWAL",
            w["amount"].to_numpy(),
        )
    )
    parts = [p for p in parts if len(p["contract"])]
    contract = np.concatenate([p["contract"] for p in parts])
    event_date = np.concatenate([p["event_date"] for p in parts]).astype(np.int64)
    event_type = np.concatenate([np.asarray(p["event_type"], dtype=object) for p in parts])
    report = np.concatenate([p["report_date"] for p in parts]).astype(np.int64)
    amount = np.concatenate([p["amount"] for p in parts]).astype(np.float64)
    order = np.lexsort((event_type.astype(str), contract, event_date))
    contract = contract[order]
    event_date = event_date[order]
    event_type = event_type[order]
    report = report[order]
    amount = amount[order]
    return pl.DataFrame(
        {
            "event_id": id_text("E", np.arange(1, len(contract) + 1), 9),
            "contract_id": ids[contract].tolist(),
            "event_date": date_series("event_date", event_date),
            "event_type": event_type.tolist(),
            "report_date": date_series("report_date", report, report < 0),
            "amount": pl.Series(np.round(amount, 2)).fill_nan(None),
            "currency": [scenario.meta.reporting_currency] * len(contract),
        }
    )


def _plain(
    contract: np.ndarray, day: np.ndarray, kind: str, amount: np.ndarray | None = None
) -> dict[str, np.ndarray]:
    n = len(contract)
    return {
        "contract": contract,
        "event_date": day,
        "event_type": np.full(n, kind, dtype=object),
        "report_date": np.full(n, -1),
        "amount": np.full(n, np.nan) if amount is None else amount,
    }


def _flow_rows(
    scenario: Scenario,
    funds: FundResult,
    ids: np.ndarray,
    window_start: int,
    cut_off: int,
    seen: np.ndarray,
) -> pl.DataFrame:
    flows = funds.flows.filter((pl.col("day") >= window_start) & (pl.col("day") <= cut_off))
    flows = flows.filter(pl.col("contract").is_in(np.flatnonzero(seen).tolist()))
    flows = flows.sort(["day", "contract", "flow_type", "amount"])
    return pl.DataFrame(
        {
            "flow_id": id_text("F", np.arange(1, flows.height + 1), 9),
            "contract_id": ids[flows["contract"].to_numpy()].tolist(),
            "flow_date": date_series("flow_date", flows["day"].to_numpy()),
            "amount": flows["amount"],
            "currency": [scenario.meta.reporting_currency] * flows.height,
            "flow_type": flows["flow_type"],
            "fund_code": flows["fund_code"],
        }
    )


# --- truth and reference tables --------------------------------------------------------------


def _reference_tables(book: LifeBook) -> dict[str, pl.DataFrame]:
    ages = np.arange(0, book.mortality.table_max_age + 1)
    mu = gompertz_makeham(book, ages)
    mortality = pl.DataFrame(
        {"age": ages, "rate_kind": ["q"] * len(ages), "rate": np.round(1.0 - np.exp(-mu), 8)}
    )
    reference, _ = _tables(book)
    rows = [
        {"product": p.key, "policy_year": k + 1, "rate": float(reference[i][k])}
        for i, p in enumerate(book.products)
        for k in range(len(p.lapse_by_policy_year))
    ]
    return {"reference_mortality": mortality, "reference_lapse": pl.DataFrame(rows)}


def _truth(
    scenario: Scenario,
    book: LifeBook,
    contracts: Contracts,
    timelines: Timelines,
    ids: np.ndarray,
    seen: np.ndarray,
    window_start: int,
    cut_off: int,
    report1: np.ndarray,
    report2: np.ndarray,
) -> dict[str, pl.DataFrame]:
    products = book.products
    keys = np.array([p.key for p in products], dtype=object)
    lapse_name = np.array([p.lapse_decrement for p in products], dtype=object)[contracts.product]
    final_cause = timelines.final_cause
    exit_type = np.array([EVENT_OF.get(int(c), "") for c in final_cause], dtype=object)
    exit_type = np.where(final_cause == LAPSE, lapse_name, exit_type)
    final_exit = timelines.final_exit
    report_final = np.where(timelines.reinstated & (timelines.cause2 == DEATH), report2, report1)
    contract_truth = pl.DataFrame(
        {
            "contract_id": ids.tolist(),
            "product": keys[contracts.product].tolist(),
            "entry_date": date_series("entry_date", contracts.entry),
            "entry_age": contracts.entry_age,
            "sex": SEX_NAMES[contracts.sex].tolist(),
            "exit_date": date_series("exit_date", final_exit, final_exit >= BIG // 2),
            "exit_type": exit_type.tolist(),
            "reinstated": timelines.reinstated,
            "reinstatement_date": date_series(
                "reinstatement_date", timelines.restart, timelines.restart >= BIG // 2
            ),
            "death_report_date": date_series(
                "death_report_date",
                report_final,
                (report_final >= BIG // 2) | (final_cause != DEATH),
            ),
            "in_data": seen,
        }
    )
    reference, true_lapse = _tables(book)
    age = np.arange(0, book.mortality.table_max_age + 1)
    mortality_rows = []
    for p in products:
        for sex, factor in ((0, book.mortality.female_factor), (1, book.mortality.male_factor)):
            mu = p.mortality_multiplier * factor * gompertz_makeham(book, age)
            mortality_rows.append(
                pl.DataFrame(
                    {
                        "product": [p.key] * len(age),
                        "sex": [SEX_NAMES[sex]] * len(age),
                        "age": age,
                        "multiplier": np.full(len(age), p.mortality_multiplier * factor),
                        "reference_force": np.round(gompertz_makeham(book, age), 10),
                        "true_force": np.round(mu, 10),
                        "true_q": np.round(1.0 - np.exp(-mu), 10),
                    }
                )
            )
    lapse_rows = []
    for i, p in enumerate(products):
        k = np.arange(len(p.lapse_by_policy_year))
        rate = true_lapse[i][k]
        lapse_rows.append(
            pl.DataFrame(
                {
                    "product": [p.key] * len(k),
                    "policy_year": k + 1,
                    "decrement": [p.lapse_decrement] * len(k),
                    "reference_rate": reference[i][k],
                    "lapse_multiplier": np.full(len(k), p.lapse_multiplier),
                    "true_rate": rate,
                    "true_force": np.round(-np.log1p(-rate), 10),
                }
            )
        )
    return {
        "life_contracts": contract_truth,
        "life_mortality_truth": pl.concat(mortality_rows),
        "life_lapse_truth": pl.concat(lapse_rows),
        "life_expected_decrements": _decrements(
            book, contracts, timelines, seen, window_start, cut_off, report1, report2
        ),
    }


def _decrements(
    book: LifeBook,
    contracts: Contracts,
    timelines: Timelines,
    seen: np.ndarray,
    window_start: int,
    cut_off: int,
    report1: np.ndarray,
    report2: np.ndarray,
) -> pl.DataFrame:
    """Central exposure, expected and actual decrements by calendar year, product, age and policy
    year over the observed window [window_start, cut_off]; expected ones use the true model."""
    products = book.products
    keys = np.array([p.key for p in products], dtype=object)
    _, true_lapse = _tables(book)
    sex_factor = np.where(
        contracts.sex == 1, book.mortality.male_factor, book.mortality.female_factor
    )
    multiplier = (
        np.array([p.mortality_multiplier for p in products])[contracts.product] * sex_factor
    )
    segments = [
        (
            contracts.entry,
            timelines.exit1,
            timelines.cause1,
            report1,
            np.ones(len(contracts), dtype=bool),
        ),
        (timelines.restart, timelines.exit2, timelines.cause2, report2, timelines.reinstated),
    ]
    exposure: list[pl.DataFrame] = []
    events: list[pl.DataFrame] = []
    keys_by_contract = keys[contracts.product]
    for start, stop, cause, report, valid in segments:
        active = seen & valid & (start < BIG // 2)
        # exposure: each policy year, cut at 1 January
        for k in range(MAX_YEARS):
            lo_k = add_months(contracts.entry, 12 * k)
            if (lo_k[active] > cut_off).all() if active.any() else True:
                break
            hi_k = add_months(contracts.entry, 12 * (k + 1))
            lo = np.maximum(np.maximum(start, lo_k), window_start)
            hi = np.minimum(np.minimum(np.minimum(stop, hi_k), cut_off + 1), contracts.maturity)
            idx = np.flatnonzero(active & (hi > lo))
            if len(idx) == 0:
                continue
            lo_i, hi_i = lo[idx], hi[idx]
            first_year, last_year = year_of(lo_i), year_of(hi_i - 1)
            cut = jan1_days(first_year + 1)
            for piece_lo, piece_hi, year, keep in (
                (lo_i, np.minimum(hi_i, cut), first_year, np.ones(len(idx), dtype=bool)),
                (cut, hi_i, last_year, last_year > first_year),
            ):
                pick = np.flatnonzero(keep & (piece_hi > piece_lo))
                if len(pick) == 0:
                    continue
                who = idx[pick]
                years = (piece_hi[pick] - piece_lo[pick]) / 365.25
                mu = multiplier[who] * gompertz_makeham(book, contracts.entry_age[who] + k)
                force = -np.log1p(-true_lapse[contracts.product[who], k])
                exposure.append(
                    pl.DataFrame(
                        {
                            "calendar_year": year[pick],
                            "product": keys_by_contract[who].tolist(),
                            "age": contracts.entry_age[who] + k,
                            "policy_year": np.full(len(who), k + 1),
                            "exposure_years": years,
                            "expected_deaths": years * mu,
                            "expected_lapses": years * force,
                        }
                    )
                )
        # actual decrements, in the cell of the day they happen
        happened = (
            active & (stop >= window_start) & (stop <= cut_off) & np.isin(cause, (DEATH, LAPSE))
        )
        idx = np.flatnonzero(happened)
        if len(idx):
            k_exit = whole_years(contracts.entry[idx], stop[idx])
            events.append(
                pl.DataFrame(
                    {
                        "calendar_year": year_of(stop[idx]),
                        "product": keys_by_contract[idx].tolist(),
                        "age": contracts.entry_age[idx] + k_exit,
                        "policy_year": k_exit + 1,
                        "deaths": (cause[idx] == DEATH).astype(np.int64),
                        "deaths_reported": (
                            (cause[idx] == DEATH) & (report[idx] <= cut_off)
                        ).astype(np.int64),
                        "lapses": (cause[idx] == LAPSE).astype(np.int64),
                    }
                )
            )
    keys_cols = ["calendar_year", "product", "age", "policy_year"]
    cells = (
        pl.concat(exposure)
        .group_by(keys_cols)
        .agg(
            pl.col("exposure_years").sum(),
            pl.col("expected_deaths").sum(),
            pl.col("expected_lapses").sum(),
        )
        if exposure
        else pl.DataFrame(schema={**{c: pl.Int64 for c in keys_cols}, "product": pl.String})
    )
    actual = (
        pl.concat(events)
        .group_by(keys_cols)
        .agg(pl.col("deaths").sum(), pl.col("deaths_reported").sum(), pl.col("lapses").sum())
        if events
        else pl.DataFrame(
            schema={
                **{c: pl.Int64 for c in keys_cols},
                "product": pl.String,
                "deaths": pl.Int64,
                "deaths_reported": pl.Int64,
                "lapses": pl.Int64,
            }
        )
    )
    both = cells.join(actual, on=keys_cols, how="full", coalesce=True).with_columns(
        pl.col("exposure_years", "expected_deaths", "expected_lapses").fill_null(0.0),
        pl.col("deaths", "deaths_reported", "lapses").fill_null(0),
    )
    return both.sort(keys_cols)
