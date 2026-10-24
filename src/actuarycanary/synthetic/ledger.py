"""The trial balance of each entity, derived from the generated premiums, claims, reserves and
expenses, with a few reconciliation differences written in on purpose.

Chart of accounts (one per entity, no split by line; ``chart()`` is the single list):

| account | name                          | class       | side   | balance        |
| ------- | ----------------------------- | ----------- | ------ | -------------- |
| 100     | Bank                          | OTHER       | debit  | period end     |
| 340     | Unearned premium provision    | UPR         | credit | period end     |
| 360     | Outstanding claims provision  | OUTSTANDING | credit | period end     |
| 590     | Result of earlier years       | OTHER       | credit | period end     |
| 600     | Gross written premium         | PREMIUM     | credit | year to date   |
| 632     | Commission expense            | COMMISSION  | debit  | year to date   |
| 650     | Reinsurance result (net cost) | RI          | debit  | year to date   |
| 660     | Investment income             | INVESTMENT  | credit | year to date   |
| 690     | Change in provisions          | OTHER       | debit  | year to date   |
| 700     | Claims paid                   | CLAIMS_PAID | debit  | year to date   |
| 770     | Operating expenses            | EXPENSE     | debit  | year to date   |
| 297     | Suspense (not in the profile) | -           | debit  | period end     |

Every journal posts equal debit and credit, so the closing balances of an entity add up to zero
in every month. Premium and commission are monthly flows converted at the average rate of the
booking month, outstanding and unearned premium are stocks at the month-end rate (CV01 as CV12
reads it), so the platform's own amounts equal the ledger's before the differences go in.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from actuarycanary.synthetic.claims import ClaimWorld
from actuarycanary.synthetic.days import month_end, month_index
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.feeds import date_series, earned_premium
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import WRITTEN_TYPES, Policies, PremiumRows
from actuarycanary.synthetic.rates import Rates, one_year_rate
from actuarycanary.synthetic.scenario import Scenario

CLASSES = ("PREMIUM", "CLAIMS_PAID", "OUTSTANDING", "UPR", "COMMISSION", "EXPENSE", "RI")
RECONCILED = CLASSES


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    account_class: str | None
    kind: str  # "PL" (year to date) or "BS" (period end)
    sign: int  # profile sign: ledger balance (debit positive) times sign is the platform's amount


def chart() -> list[Account]:
    return [
        Account("100", "Banka", "OTHER", "BS", 1),
        Account("340", "Kazanılmamış prim karşılığı", "UPR", "BS", -1),
        Account("360", "Muallak hasar karşılığı", "OUTSTANDING", "BS", -1),
        Account("590", "Geçmiş yıllar kârı", "OTHER", "BS", -1),
        Account("600", "Yazılan primler", "PREMIUM", "PL", -1),
        Account("632", "Komisyon giderleri", "COMMISSION", "PL", 1),
        Account("650", "Reasürans net maliyeti", "RI", "PL", 1),
        Account("660", "Yatırım gelirleri", "INVESTMENT", "PL", -1),
        Account("690", "Teknik karşılıklardaki değişim", "OTHER", "PL", 1),
        Account("700", "Ödenen hasarlar", "CLAIMS_PAID", "PL", 1),
        Account("770", "Faaliyet giderleri", "EXPENSE", "PL", 1),
        Account("297", "Askı hesabı", None, "BS", 1),
    ]


def mapping_profile() -> pl.DataFrame:
    """The account-mapping profile that fits this chart (the suspense account is not in it)."""
    rows = [
        {
            "entity": None,
            "account_pattern": f"{a.code}*",
            "account_class": a.account_class,
            "sign": a.sign,
            "balance_kind": "YEAR_TO_DATE" if a.kind == "PL" else "PERIOD",
            "line": None,
        }
        for a in chart()
        if a.account_class is not None
    ]
    return pl.DataFrame(rows, schema_overrides={"entity": pl.String, "line": pl.String})


# --- inputs ------------------------------------------------------------------------------


def period_rates(
    scenario: Scenario, market: Market, first_month: int, last_month: int
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Average and month-end exchange rates per currency for each month, as the market file writes
    them (FX_PERIOD_AVERAGE rounded to six decimals, FX_PERIOD_END)."""
    cut_off = market.cut_off_day
    days = np.arange(market.base_day, cut_off + 1)
    base_month = int(month_index(market.base_day))
    months = np.arange(base_month, int(month_index(cut_off)) + 1)
    ends = month_end(months)
    average: dict[str, np.ndarray] = {}
    end: dict[str, np.ndarray] = {}
    month_of_day = month_index(days) - months[0]
    for code in market.fx:
        daily = market.fx[code][: len(days)]
        average[code] = np.round(
            np.bincount(month_of_day, weights=daily) / np.bincount(month_of_day), 6
        )
        end[code] = market.fx[code][np.minimum(ends, days[-1]) - market.base_day]
    wanted = np.arange(first_month, last_month + 1) - base_month
    reporting = scenario.meta.reporting_currency
    return (
        {reporting: np.ones(len(wanted)), **{c: v[wanted] for c, v in average.items()}},
        {reporting: np.ones(len(wanted)), **{c: v[wanted] for c, v in end.items()}},
    )


@dataclass
class _Flows:
    """Monthly amounts in the reporting currency, by entity, over the ledger's month axis."""

    written: dict[str, np.ndarray]
    written_foreign_average: dict[str, np.ndarray]  # the part written in a foreign currency
    written_foreign_end: dict[str, np.ndarray]  # the same part at the month-end rate
    commission: dict[str, np.ndarray]
    ceded_premium: dict[str, np.ndarray]
    ri_commission: dict[str, np.ndarray]
    claims_paid: dict[str, np.ndarray]
    ceded_paid: dict[str, np.ndarray]
    expenses: dict[str, np.ndarray]
    outstanding: dict[str, np.ndarray]  # stock at month end
    upr: dict[str, np.ndarray]  # stock at month end


def _axis(
    frame: pl.DataFrame, key: str, value: str, entities: list[str], first_month: int, n: int
) -> dict[str, np.ndarray]:
    out = {e: np.zeros(n) for e in entities}
    if frame.height == 0:
        return out
    for e in entities:
        mine = frame.filter(pl.col(key) == e)
        if mine.height == 0:
            continue
        at = mine["month"].to_numpy() - first_month
        keep = (at >= 0) & (at < n)
        np.add.at(out[e], at[keep], mine[value].to_numpy()[keep])
    return out


def _rate_frame(
    average: dict[str, np.ndarray], end: dict[str, np.ndarray], first: int
) -> pl.DataFrame:
    rows = [
        pl.DataFrame(
            {
                "currency": [code] * len(average[code]),
                "month": first + np.arange(len(average[code])),
                "avg": average[code],
                "end": end[code],
            }
        )
        for code in average
    ]
    return pl.concat(rows)


def _flows(
    scenario: Scenario,
    policies: Policies,
    premiums: PremiumRows,
    world: ClaimWorld,
    valuations: pl.DataFrame,
    claim: np.ndarray,
    day: np.ndarray,
    expenses: pl.DataFrame,
    rates: pl.DataFrame,
    entities: list[str],
    first_month: int,
    n: int,
) -> _Flows:
    reporting = scenario.meta.reporting_currency
    # premium transactions
    pol = premiums.policy
    pf = pl.DataFrame(
        {
            "entity": policies.entity[pol].tolist(),
            "currency": policies.currency[pol].tolist(),
            "month": month_index(premiums.booking),
            "type": premiums.type.tolist(),
            "amount": premiums.amount,
        }
    ).join(rates, on=["currency", "month"], how="left")
    pf = pf.with_columns(
        (pl.col("amount") * pl.col("avg")).alias("try"),
        (pl.col("amount") * pl.col("end")).alias("try_end"),
        (pl.col("currency") != reporting).alias("foreign"),
    )

    def by_type(kind: list[str], column: str = "try", foreign: bool | None = None) -> pl.DataFrame:
        sel = pf.filter(pl.col("type").is_in(kind))
        if foreign is not None:
            sel = sel.filter(pl.col("foreign") == foreign)
        return sel.group_by(["entity", "month"]).agg(pl.col(column).sum())

    def axis(frame: pl.DataFrame, column: str) -> dict[str, np.ndarray]:
        return {
            e: np.round(a, 2)
            for e, a in _axis(frame, "entity", column, entities, first_month, n).items()
        }

    written = by_type(list(WRITTEN_TYPES))
    foreign_avg = by_type(list(WRITTEN_TYPES), foreign=True)
    foreign_end = by_type(list(WRITTEN_TYPES), "try_end", foreign=True)

    # claims: paid flows and reserve stocks from the clean valuation rows
    month = month_index(day)
    cf = pl.DataFrame(
        {
            "claim": claim,
            "month": month,
            "paid": valuations["paid_to_date"].to_numpy(),
            "reserve": valuations["case_reserve"].to_numpy(),
            "cpaid": valuations["ceded_paid_to_date"].to_numpy(),
        }
    ).sort(["claim", "month"])
    who = cf["claim"].to_numpy()
    cf = cf.with_columns(
        pl.Series("entity", world.c_entity[who].tolist()),
        pl.Series("currency", world.c_currency[who].tolist()),
    )
    cf = cf.with_columns(
        (pl.col("paid") - pl.col("paid").shift(1).over("claim").fill_null(0.0)).alias("paid_flow"),
        (pl.col("cpaid") - pl.col("cpaid").shift(1).over("claim").fill_null(0.0)).alias(
            "cpaid_flow"
        ),
    ).join(rates, on=["currency", "month"], how="left")
    cf = cf.with_columns(
        (pl.col("paid_flow") * pl.col("avg")).alias("paid_try"),
        (pl.col("cpaid_flow") * pl.col("avg")).alias("cpaid_try"),
        (pl.col("reserve") * pl.col("end")).alias("reserve_try"),
    )
    paid = cf.group_by(["entity", "month"]).agg(pl.col("paid_try").sum())
    cpaid = cf.group_by(["entity", "month"]).agg(pl.col("cpaid_try").sum())
    reserve = cf.group_by(["entity", "month"]).agg(pl.col("reserve_try").sum())

    # expenses (reporting currency already)
    ef = expenses.select(
        pl.col("entity"),
        pl.col("period").dt.year().alias("y"),
        pl.col("period").dt.month().alias("m"),
        pl.col("amount"),
    ).with_columns(((pl.col("y") - 1970) * 12 + pl.col("m") - 1).alias("month"))
    exp = ef.group_by(["entity", "month"]).agg(pl.col("amount").sum())

    # unearned premium: written to date minus earned to date, per group, at the month-end rate
    lines = list(scenario.lines)
    currencies = sorted(set(policies.currency.tolist()), key=lambda c: (c != reporting, c))
    earned, m0, m1 = earned_premium(policies, premiums, lines, entities, currencies)
    last = first_month + n - 1
    upr = {e: np.zeros(n) for e in entities}
    written_rows = np.isin(premiums.type, WRITTEN_TYPES)
    wpol = premiums.policy[written_rows]
    n_e, n_c = len(entities), len(currencies)
    group = (
        np.array([lines.index(x) for x in policies.line], dtype=np.int64)[wpol] * (n_e * n_c)
        + np.array([entities.index(x) for x in policies.entity], dtype=np.int64)[wpol] * n_c
        + np.array([currencies.index(x) for x in policies.currency], dtype=np.int64)[wpol]
    )
    book = month_index(premiums.booking[written_rows])
    span = np.arange(min(first_month, m0, int(book.min())), last + 1)
    cum_written = np.zeros((len(lines) * n_e * n_c, len(span)))
    np.add.at(cum_written, (group, book - span[0]), premiums.amount[written_rows])
    cum_written = np.cumsum(cum_written, axis=1)
    cum_earned = np.zeros_like(cum_written)
    width = min(earned.shape[1], len(span) - (m0 - span[0]))
    cum_earned[:, m0 - span[0] : m0 - span[0] + width] = earned[:, :width]
    cum_earned = np.cumsum(cum_earned, axis=1)
    stock = cum_written - cum_earned
    wanted = np.arange(first_month, last + 1) - span[0]
    for li in range(len(lines)):
        for ei, entity in enumerate(entities):
            for ci, currency in enumerate(currencies):
                series = stock[(li * n_e + ei) * n_c + ci, wanted]
                if currency != reporting:
                    series = series * rates_end(rates, currency, first_month, n)
                upr[entity] += np.round(series, 2)

    return _Flows(
        written=axis(written, "try"),
        written_foreign_average=axis(foreign_avg, "try"),
        written_foreign_end=axis(foreign_end, "try_end"),
        commission=axis(by_type(["COMMISSION"]), "try"),
        ceded_premium=axis(by_type(["CEDED_PREMIUM"]), "try"),
        ri_commission=axis(by_type(["RI_COMMISSION"]), "try"),
        claims_paid=axis(paid, "paid_try"),
        ceded_paid=axis(cpaid, "cpaid_try"),
        expenses=axis(exp, "amount"),
        outstanding=axis(reserve, "reserve_try"),
        upr={e: np.round(v, 2) for e, v in upr.items()},
    )


def rates_end(rates: pl.DataFrame, currency: str, first_month: int, n: int) -> np.ndarray:
    sub = rates.filter(pl.col("currency") == currency).sort("month")
    at = sub["month"].to_numpy() - first_month
    out = np.ones(n)
    keep = (at >= 0) & (at < n)
    out[at[keep]] = sub["end"].to_numpy()[keep]
    return out


# --- the books -----------------------------------------------------------------------------


@dataclass
class Ledger:
    frame: pl.DataFrame
    platform: pl.DataFrame  # entity, class, period, platform_amount (before the differences)
    differences: pl.DataFrame
    profile: pl.DataFrame
    gaps: pl.DataFrame  # entity, class, period, platform, ledger, gap, cause


def build_ledger(
    scenario: Scenario,
    size_first_month: int,
    market: Market,
    policies: Policies,
    premiums: PremiumRows,
    world: ClaimWorld,
    valuations: pl.DataFrame,
    claim: np.ndarray,
    day: np.ndarray,
    expenses: pl.DataFrame,
    rates: Rates,
    streams: Streams,
) -> Ledger:
    params = scenario.phase2.ledger
    last_month = int(month_index(market.cut_off_day))
    first_month = size_first_month
    n = last_month - first_month + 1
    months = np.arange(first_month, last_month + 1)
    entities = [e.id for e in scenario.entities]
    average, end = period_rates(scenario, market, first_month, last_month)
    rate_table = _rate_frame(average, end, first_month)
    flows = _flows(
        scenario,
        policies,
        premiums,
        world,
        valuations,
        claim,
        day,
        expenses,
        rate_table,
        entities,
        first_month,
        n,
    )
    reporting = scenario.meta.reporting_currency
    accounts = {a.code: a for a in chart()}
    fiscal_start = (months % 12) + 1 == params.fiscal_year_start_month

    # platform amounts, per entity and class (the values the measures would give)
    platform_amount: dict[tuple[str, str], np.ndarray] = {}
    for e in entities:
        platform_amount[(e, "PREMIUM")] = flows.written[e]
        platform_amount[(e, "COMMISSION")] = flows.commission[e]
        platform_amount[(e, "CLAIMS_PAID")] = flows.claims_paid[e]
        platform_amount[(e, "EXPENSE")] = flows.expenses[e]
        platform_amount[(e, "OUTSTANDING")] = flows.outstanding[e]
        platform_amount[(e, "UPR")] = flows.upr[e]
        platform_amount[(e, "RI")] = np.round(
            flows.ceded_premium[e] - flows.ri_commission[e] - flows.ceded_paid[e], 2
        )

    # the figures the ledger books; differences change these, not the platform amounts
    booked: dict[str, dict[str, np.ndarray]] = {
        e: {
            "written": flows.written[e].copy(),
            "outstanding": flows.outstanding[e].copy(),
        }
        for e in entities
    }
    differences: list[dict[str, object]] = []
    rng = streams.get("phase2", "ledger", "differences")

    def period(i: int) -> object:
        return date_series("period", np.array([month_end(months[i])]))[0]

    def pick_month(low: float = 0.15, high: float = 0.85) -> int:
        return int(rng.integers(int(n * low), max(int(n * high), int(n * low) + 1)))

    by_size = sorted(entities, key=lambda e: -float(flows.written[e].sum()))
    diff = params.differences
    # (a) a month of premium booked one month late
    for k in range(diff.premium_timing_months):
        e = by_size[k % len(by_size)]
        i = pick_month()
        amount = float(booked[e]["written"][i])
        if i + 1 < n and amount != 0.0:
            booked[e]["written"][i] = 0.0
            booked[e]["written"][i + 1] += amount
            differences.append(
                _difference(
                    "premium_timing",
                    e,
                    "600",
                    period(i),
                    -amount,
                    "premium of the month booked in the next month (cut-off timing)",
                )
            )
            differences.append(
                _difference(
                    "premium_timing",
                    e,
                    "600",
                    period(i + 1),
                    amount,
                    "premium of the month before booked in this month (cut-off timing)",
                )
            )
    # (d) foreign premium translated at the month-end rate instead of the average rate
    for _ in range(diff.translation_months):
        best = max(entities, key=lambda e: float(np.abs(flows.written_foreign_average[e]).max()))
        series = np.abs(flows.written_foreign_average[best])
        i = int(np.argmax(series))
        if series[i] > 0:
            shift = round(
                float(flows.written_foreign_end[best][i] - flows.written_foreign_average[best][i]),
                2,
            )
            booked[best]["written"][i] = round(float(booked[best]["written"][i]) + shift, 2)
            differences.append(
                _difference(
                    "translation",
                    best,
                    "600",
                    period(i),
                    shift,
                    "foreign-currency premium translated at the month-end rate (currency)",
                )
            )
    # (c) one entity books an IBNR loading in its outstanding provision from some month on
    if diff.outstanding_with_ibnr_share > 0:
        e = by_size[0]
        start = int(n * 0.6)
        extra = np.round(booked[e]["outstanding"] * diff.outstanding_with_ibnr_share, 2)
        extra[:start] = 0.0
        booked[e]["outstanding"] = np.round(booked[e]["outstanding"] + extra, 2)
        for i in np.flatnonzero(extra != 0):
            differences.append(
                _difference(
                    "ibnr_in_outstanding",
                    e,
                    "360",
                    period(int(i)),
                    float(extra[i]),
                    "the ledger outstanding includes an IBNR loading",
                )
            )

    # journals -> net postings per entity and account (debit positive)
    rows: list[pl.DataFrame] = []
    investments: dict[str, np.ndarray] = {}
    for e in entities:
        w, k = booked[e]["written"], flows.commission[e]
        y, x = flows.claims_paid[e], flows.expenses[e]
        ri = np.round(flows.ceded_premium[e] - flows.ri_commission[e] - flows.ceded_paid[e], 2)
        out_stock, upr_stock = booked[e]["outstanding"], flows.upr[e]
        d_out = np.round(np.diff(out_stock, prepend=0.0), 2)
        d_upr = np.round(np.diff(upr_stock, prepend=0.0), 2)
        total = out_stock + upr_stock
        lagged = np.concatenate([[0.0], total[:-1]])
        year_rate = one_year_rate(rates, reporting, months)
        inv = np.round(lagged * year_rate / 12.0, 2)
        investments[e] = inv
        post: dict[str, np.ndarray] = {
            "600": -w,
            "632": k,
            "700": y,
            "650": ri,
            "770": x,
            "660": -inv,
            "690": d_out + d_upr,
            "360": -d_out,
            "340": -d_upr,
        }
        post["100"] = w - k - y - ri - x + inv
        if diff.unmapped_account and e == by_size[min(1, len(by_size) - 1)]:
            i = pick_month(0.3, 0.7)
            amount = round(float(np.mean(np.abs(w[w != 0]))) * 0.015, 2) if (w != 0).any() else 0.0
            post["297"] = np.zeros(n)
            post["297"][i] = amount
            post["100"][i] -= amount
            differences.append(
                _difference(
                    "unmapped_account",
                    e,
                    "297",
                    period(i),
                    amount,
                    "an amount booked to a suspense account that the profile does not map",
                )
            )
        rows.append(_balances(e, post, accounts, fiscal_start, months, scenario))

    frame = pl.concat(rows)
    # (e) one account row of one entity left out for a month
    if diff.missing_months:
        e = by_size[-1]
        i = pick_month(0.4, 0.6)
        gone = month_end(months[i])
        before = frame.height
        frame = frame.filter(
            ~(
                (pl.col("entity") == e)
                & (pl.col("account") == "690")
                & (pl.col("period") == date_series("period", np.array([gone]))[0])
            )
        )
        if frame.height < before:
            differences.append(
                _difference(
                    "missing_row", e, "690", period(i), 0.0, "the account has no row for the month"
                )
            )
    frame = frame.sort(["entity", "period", "account"])
    profile = mapping_profile()
    platform = pl.concat(
        [
            pl.DataFrame(
                {
                    "entity": [e] * n,
                    "account_class": [c] * n,
                    "period": date_series("period", month_end(months)),
                    "platform_amount": platform_amount[(e, c)],
                }
            )
            for e in entities
            for c in CLASSES
        ]
    )
    diff_table = _difference_table(differences)
    gaps = reconcile(
        frame, profile, platform, scenario.phase2.ledger.fiscal_year_start_month, diff_table
    )
    return Ledger(frame, platform, diff_table, profile, gaps)


def _difference(
    kind: str, entity: str, account: str, period: object, amount: float, cause: str
) -> dict[str, object]:
    return {
        "kind": kind,
        "entity": entity,
        "account": account,
        "period": period,
        "ledger_minus_platform": amount,
        "cause": cause,
    }


def _difference_table(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "kind": pl.String,
            "entity": pl.String,
            "account": pl.String,
            "period": pl.Date,
            "ledger_minus_platform": pl.Float64,
            "cause": pl.String,
        },
    ).sort(["entity", "period", "kind"])


def _balances(
    entity: str,
    post: dict[str, np.ndarray],
    accounts: dict[str, Account],
    fiscal_start: np.ndarray,
    months: np.ndarray,
    scenario: Scenario,
) -> pl.DataFrame:
    """Opening, debit, credit and closing balance of every account of one entity."""
    n = len(months)
    closing: dict[str, np.ndarray] = {}
    opening: dict[str, np.ndarray] = {}
    for code, net in post.items():
        net = np.round(net, 2)
        close = np.zeros(n)
        open_ = np.zeros(n)
        running = 0.0
        for i in range(n):
            if accounts[code].kind == "PL" and fiscal_start[i]:
                running = 0.0
            open_[i] = running
            running = round(running + net[i], 2)
            close[i] = running
        closing[code], opening[code] = close, open_
    # the result of a finished year moves to the result of earlier years at the next year start
    result_move = np.zeros(n)
    for i in range(1, n):
        if fiscal_start[i]:
            result_move[i] = round(
                sum(
                    closing[c][i - 1]
                    for c, a in accounts.items()
                    if c in closing and a.kind == "PL"
                ),
                2,
            )
    running = 0.0
    close, open_ = np.zeros(n), np.zeros(n)
    for i in range(n):
        open_[i] = running
        running = round(running + result_move[i], 2)
        close[i] = running
    post = {**post, "590": result_move}
    closing["590"], opening["590"] = close, open_

    segment = scenario_entity_segment(scenario, entity)
    parts: list[pl.DataFrame] = []
    for code, net in post.items():
        net = np.round(net, 2)
        live = (np.abs(net) > 0) | (np.abs(closing[code]) > 0) | (np.abs(opening[code]) > 0)
        keep = np.flatnonzero(live)
        if len(keep) == 0:
            continue
        a = accounts[code]
        parts.append(
            pl.DataFrame(
                {
                    "entity": [entity] * len(keep),
                    "account": [code] * len(keep),
                    "period": date_series("period", month_end(months[keep])),
                    "closing_balance": closing[code][keep],
                    "opening_balance": opening[code][keep],
                    "debit": np.where(net[keep] > 0, net[keep], 0.0),
                    "credit": np.where(net[keep] < 0, -net[keep], 0.0),
                    "currency": [scenario.meta.reporting_currency] * len(keep),
                    "account_name": [a.name] * len(keep),
                    "account_class": [a.account_class] * len(keep),
                    "segment": [segment] * len(keep),
                }
            )
        )
    return pl.concat(parts)


def scenario_entity_segment(scenario: Scenario, entity: str) -> str | None:
    for e in scenario.entities:
        if e.id == entity:
            return e.segments[0] if len(e.segments) == 1 else None
    return None


# --- reading the ledger back -----------------------------------------------------------------


def mapped_amounts(
    frame: pl.DataFrame, profile: pl.DataFrame, fiscal_start_month: int
) -> pl.DataFrame:
    """Platform-signed amount per entity, class and month from the ledger and the profile (CV12).

    Year-to-date accounts become monthly movements by differencing within the fiscal year;
    period-end accounts are stocks. Accounts the profile lacks are left out."""
    rules = profile.to_dicts()
    code_class: dict[str, dict[str, object]] = {}
    for account in frame["account"].unique().to_list():
        best = None
        for rule in rules:
            pattern = str(rule["account_pattern"])
            hit = account.startswith(pattern[:-1]) if pattern.endswith("*") else account == pattern
            if hit and (best is None or len(pattern) > len(str(best["account_pattern"]))):
                best = rule
        if best is not None:
            code_class[account] = best
    mapped = frame.filter(pl.col("account").is_in(list(code_class)))
    mapped = mapped.with_columns(
        pl.col("account")
        .replace_strict({a: r["account_class"] for a, r in code_class.items()})
        .alias("account_class_mapped"),
        pl.col("account")
        .replace_strict({a: r["sign"] for a, r in code_class.items()}, return_dtype=pl.Int64)
        .alias("sign"),
        pl.col("account")
        .replace_strict({a: r["balance_kind"] for a, r in code_class.items()})
        .alias("balance_kind"),
    )
    mapped = mapped.with_columns(
        pl.when(pl.col("balance_kind") == "YEAR_TO_DATE")
        .then(
            pl.when(pl.col("period").dt.month() == fiscal_start_month)
            .then(pl.col("closing_balance"))
            .otherwise(pl.col("closing_balance") - pl.col("opening_balance"))
        )
        .otherwise(pl.col("closing_balance"))
        .alias("amount")
    ).with_columns((pl.col("amount") * pl.col("sign")).alias("signed"))
    return (
        mapped.group_by(["entity", "account_class_mapped", "period"])
        .agg(pl.col("signed").sum().round(2).alias("ledger_amount"))
        .rename({"account_class_mapped": "account_class"})
        .sort(["entity", "account_class", "period"])
    )


def reconcile(
    frame: pl.DataFrame,
    profile: pl.DataFrame,
    platform: pl.DataFrame,
    fiscal_start_month: int,
    differences: pl.DataFrame,
) -> pl.DataFrame:
    """The reconciliation table of the truth: platform minus ledger per entity, class and month,
    with the cause when a difference was written in."""
    ledger = mapped_amounts(frame, profile, fiscal_start_month)
    both = platform.join(ledger, on=["entity", "account_class", "period"], how="left").with_columns(
        pl.col("ledger_amount").fill_null(0.0)
    )
    both = both.with_columns(
        (pl.col("platform_amount") - pl.col("ledger_amount")).round(2).alias("gap")
    )
    causes = (
        differences.with_columns(
            pl.when(pl.col("account") == "600")
            .then(pl.lit("PREMIUM"))
            .when(pl.col("account") == "360")
            .then(pl.lit("OUTSTANDING"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("account_class")
        )
        .filter(pl.col("account_class").is_not_null())
        .group_by(["entity", "account_class", "period"])
        .agg(pl.col("kind").first().alias("cause"))
    )
    return both.join(causes, on=["entity", "account_class", "period"], how="left").sort(
        ["entity", "account_class", "period"]
    )


MONEY_COLUMNS_LEDGER = {
    "ledger_gaps": {
        c: ("reporting", "ledger and platform amounts are in the reporting currency")
        for c in ("platform_amount", "ledger_amount", "gap")
    },
    "ledger_differences": {"ledger_minus_platform": ("reporting", "reporting currency")},
}
