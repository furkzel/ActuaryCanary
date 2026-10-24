"""Ground truth: what the simulation knows and the data files do not.

Every money column carries its currency (``MONEY_COLUMNS``, written to ``truth/money_columns.csv``):
either the row's own ``currency`` column ("row") or the reporting currency, TRY ("reporting"),
which the column name says. Amounts are never added across rows of different currencies unless
they are in the reporting currency. "base prices" means the inflation-free units of the money
mechanics (the reporting currency at the base date's prices and starting rates).
"""

from datetime import date

import numpy as np
import polars as pl

from actuarycanary.synthetic.claims import END_OF_TIME, REGULAR, SHOCK, ClaimWorld, Cumulative
from actuarycanary.synthetic.days import (
    DAYS_PER_YEAR,
    month_end,
    month_index,
    to_day,
    year_of,
    years_since,
)
from actuarycanary.synthetic.draws import mean_of
from actuarycanary.synthetic.feeds import earned_premium
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import Policies, PremiumRows, simulation_years
from actuarycanary.synthetic.reinsurance import Reinsurance
from actuarycanary.synthetic.scenario import Scenario, SizeSpec

MAX_LAG_YEARS = 10

ROW, REPORTING = "row", "reporting"
_ULTIMATES_ROW = [
    "ultimate_gross",
    "ultimate_ceded",
    "ultimate_net",
    "ultimate_subrogation",
    "ultimate_salvage",
    "ultimate_allocated_expense",
    "paid_at_cutoff",
    "case_reserve_at_cutoff",
    "incurred_at_cutoff",
    "ibnr_at_cutoff",
    "earned_premium",
]
_ULTIMATES_REPORTING = {
    "ultimate_base_prices_try": "claim cost at base-date prices times the starting rate",
    "ultimate_ceded_base_prices_try": "claim cost at base-date prices times the starting rate",
    "ultimate_net_base_prices_try": "claim cost at base-date prices times the starting rate",
    "ultimate_try_at_payment_spot": "each payment at the spot rate of its day",
    "ultimate_try_at_cutoff_prices": "spot rate of the payment day, restated to cut-off prices",
    "ultimate_try_at_cutoff_rate": "ultimate_gross at the constant rate of the cut-off (CV01)",
    "earned_premium_try_at_cutoff_rate": "earned_premium at the constant cut-off rate (CV01)",
}
# file -> column -> (currency basis, how a reporting-currency amount was converted)
MONEY_COLUMNS: dict[str, dict[str, tuple[str, str]]] = {
    "ultimates": {
        **{c: (ROW, "") for c in _ULTIMATES_ROW},
        **{c: (REPORTING, how) for c, how in _ULTIMATES_REPORTING.items()},
    },
    "ibnr_by_valuation": {
        c: (ROW, "") for c in ("ultimate", "paid", "case_reserve", "incurred", "ibnr_true")
    },
    "frequency_severity": {
        "mean_base_severity_try": (
            REPORTING,
            "claim cost at base-date prices times the starting rate",
        ),
        "expected_base_severity_try": (REPORTING, "parameters at base-date prices, in TRY"),
    },
    "development_pattern": {},
    "inflation": {},
}


def money_columns_table(
    columns_by_file: dict[str, dict[str, tuple[str, str]]] | None = None,
) -> pl.DataFrame:
    """Which currency each money column of each truth file is in (truth/money_columns.csv; the
    files of the later feeds are in truth/money_columns_phase2.csv)."""
    rows = [
        {"file": f"{name}.csv", "column": column, "currency": basis, "conversion": how}
        for name, columns in (MONEY_COLUMNS if columns_by_file is None else columns_by_file).items()
        for column, (basis, how) in columns.items()
    ]
    return pl.DataFrame(
        rows,
        schema={
            "file": pl.String,
            "column": pl.String,
            "currency": pl.String,
            "conversion": pl.String,
        },
    )


def _year_end(year: int) -> int:
    return to_day(date(year, 12, 31))


def _claim_frame(
    scenario: Scenario, world: ClaimWorld, reinsurance: Reinsurance, market: Market, cut_off: int
) -> pl.DataFrame:
    """One row per simulated claim with its final amounts and its state at the cut-off."""
    claim = np.arange(len(world))
    final = world.ultimate()
    ceded_paid, _ = reinsurance.ceded(
        claim, np.full(len(world), END_OF_TIME), final["paid"], np.zeros(len(world))
    )
    ceded_paid = np.minimum(ceded_paid, final["paid"])
    at_cut = world.state(claim, np.full(len(world), cut_off))

    pay_fx = np.ones(len(world.p_claim))
    for code in market.fx:
        mask = world.c_currency[world.p_claim] == code
        pay_fx[mask] = market.fx_at(code, world.p_day[mask])
    restate = market.price_factor(np.array([cut_off]))[0] / market.price_factor(world.p_day)
    paid_try_spot = np.bincount(
        world.p_claim, weights=world.p_amount * pay_fx, minlength=len(world)
    )
    paid_cut_prices = np.bincount(
        world.p_claim, weights=world.p_amount * pay_fx * restate, minlength=len(world)
    )
    fx_cut = np.array(
        [
            market.fx_at(c, np.array([cut_off]))[0] if c in market.fx else 1.0
            for c in world.c_currency
        ]
    )
    # ceded share of each claim, applied to its cost at base prices (exact for a quota share)
    ceded_share = np.divide(
        ceded_paid, final["paid"], out=np.zeros(len(world)), where=final["paid"] > 0
    )
    base_prices = np.where(world.c_nil, 0.0, world.c_cost * world.c_fx_start)
    return pl.DataFrame(
        {
            "segment": [scenario.lines[ln].segment for ln in world.c_line],
            "line": world.c_line.tolist(),
            "entity": world.c_entity.tolist(),
            "currency": world.c_currency.tolist(),
            "accident_year": year_of(world.c_occ),
            "kind": world.c_kind,
            "nil": world.c_nil,
            "reported": world.c_rep <= cut_off,
            "ultimate_gross": final["paid"],
            "ultimate_ceded": ceded_paid,
            "ultimate_base_prices_try": base_prices,
            "ultimate_ceded_base_prices_try": base_prices * ceded_share,
            "ultimate_try_at_payment_spot": paid_try_spot,
            "ultimate_try_at_cutoff_prices": paid_cut_prices,
            "ultimate_try_at_cutoff_rate": final["paid"] * fx_cut,
            "ultimate_subrogation": final["subrogation"],
            "ultimate_salvage": final["salvage"],
            "ultimate_allocated_expense": final["expense"],
            "paid_at_cutoff": at_cut["paid"],
            "case_reserve_at_cutoff": at_cut["reserve"],
        }
    )


def exposure_by_year(scenario: Scenario, size: SizeSpec, policies: Policies) -> pl.DataFrame:
    """Earned exposure in unit-years per line and accident year (CV04 exposure)."""
    first_year, last_year = simulation_years(scenario, size)
    window_hi = to_day(date(last_year + 1, 1, 1))
    rows = []
    for year in range(first_year, last_year + 1):
        lo = np.maximum(policies.start, to_day(date(year, 1, 1)))
        hi = np.minimum(
            np.minimum(policies.end, policies.cancel), min(to_day(date(year + 1, 1, 1)), window_hi)
        )
        years = policies.units * np.maximum(hi - lo, 0) / DAYS_PER_YEAR
        for line in scenario.lines:
            rows.append(
                {
                    "line": line,
                    "accident_year": year,
                    "exposure_years": float(years[policies.line == line].sum()),
                }
            )
    return pl.DataFrame(rows)


def ultimates(
    scenario: Scenario,
    size: SizeSpec,
    claims: pl.DataFrame,
    policies: Policies,
    premiums: PremiumRows,
    market: Market,
    cut_off: int,
) -> pl.DataFrame:
    lines = list(scenario.lines)
    entities = [e.id for e in scenario.entities]
    currencies = sorted(
        set(policies.currency.tolist()), key=lambda c: (c != scenario.meta.reporting_currency, c)
    )
    monthly, m0, _ = earned_premium(policies, premiums, lines, entities, currencies)
    first_year, last_year = simulation_years(scenario, size)
    premium_rows = []
    for li, line in enumerate(lines):
        for ei, entity in enumerate(entities):
            for ci, currency in enumerate(currencies):
                series = monthly[(li * len(entities) + ei) * len(currencies) + ci]
                for year in range(first_year, last_year + 1):
                    lo, hi = (
                        int(month_index(to_day(date(year, 1, 1)))) - m0,
                        int(month_index(to_day(date(year, 12, 31)))) - m0 + 1,
                    )
                    total = float(series[max(lo, 0) : max(hi, 0)].sum()) if hi > 0 else 0.0
                    if total != 0.0:
                        premium_rows.append(
                            {
                                "line": line,
                                "entity": entity,
                                "currency": currency,
                                "accident_year": year,
                                "earned_premium": total,
                            }
                        )
    premium = pl.DataFrame(
        premium_rows,
        schema={
            "line": pl.String,
            "entity": pl.String,
            "currency": pl.String,
            "accident_year": pl.Int64,
            "earned_premium": pl.Float64,
        },
    )
    keys = ["line", "entity", "currency", "accident_year"]
    grouped = claims.group_by(["segment", *keys]).agg(
        pl.len().alias("claims_simulated"),
        (~pl.col("nil")).sum().alias("claims_non_nil"),
        pl.col("reported").sum().alias("claims_reported_at_cutoff"),
        pl.col("ultimate_gross").sum(),
        pl.col("ultimate_ceded").sum(),
        pl.col("ultimate_base_prices_try").sum(),
        pl.col("ultimate_ceded_base_prices_try").sum(),
        pl.col("ultimate_try_at_payment_spot").sum(),
        pl.col("ultimate_try_at_cutoff_prices").sum(),
        pl.col("ultimate_try_at_cutoff_rate").sum(),
        pl.col("ultimate_subrogation").sum(),
        pl.col("ultimate_salvage").sum(),
        pl.col("ultimate_allocated_expense").sum(),
        pl.col("paid_at_cutoff").sum(),
        (pl.col("case_reserve_at_cutoff") * pl.col("reported"))
        .sum()
        .alias("case_reserve_at_cutoff"),
    )
    segment_of = {name: line.segment for name, line in scenario.lines.items()}
    table = grouped.join(premium, on=keys, how="full", coalesce=True)
    table = table.with_columns(
        pl.col("line").replace_strict(segment_of, return_dtype=pl.String).alias("segment")
    ).fill_null(0)
    rate_at_cut_off = {
        c: float(market.fx_at(c, np.array([cut_off]))[0]) if c in market.fx else 1.0
        for c in currencies
    }
    return (
        table.with_columns(
            pl.col("currency")
            .replace_strict(rate_at_cut_off, return_dtype=pl.Float64)
            .alias("fx_cutoff_rate"),
            (pl.col("ultimate_gross") - pl.col("ultimate_ceded")).alias("ultimate_net"),
            (pl.col("ultimate_base_prices_try") - pl.col("ultimate_ceded_base_prices_try")).alias(
                "ultimate_net_base_prices_try"
            ),
            (pl.col("paid_at_cutoff") + pl.col("case_reserve_at_cutoff")).alias(
                "incurred_at_cutoff"
            ),
        )
        .with_columns(
            (pl.col("ultimate_gross") - pl.col("incurred_at_cutoff")).alias("ibnr_at_cutoff"),
            pl.when(pl.col("earned_premium") > 0)
            .then(pl.col("ultimate_gross") / pl.col("earned_premium"))
            .otherwise(None)
            .alias("ultimate_loss_ratio"),
        )
        .select(
            "segment",
            "line",
            "entity",
            "accident_year",
            "currency",
            "claims_simulated",
            "claims_non_nil",
            "claims_reported_at_cutoff",
            "ultimate_gross",
            "ultimate_ceded",
            "ultimate_net",
            "ultimate_base_prices_try",
            "ultimate_ceded_base_prices_try",
            "ultimate_net_base_prices_try",
            "ultimate_try_at_payment_spot",
            "ultimate_try_at_cutoff_prices",
            "ultimate_try_at_cutoff_rate",
            "ultimate_subrogation",
            "ultimate_salvage",
            "ultimate_allocated_expense",
            "paid_at_cutoff",
            "case_reserve_at_cutoff",
            "incurred_at_cutoff",
            "ibnr_at_cutoff",
            "earned_premium",
            "fx_cutoff_rate",
            (pl.col("earned_premium") * pl.col("fx_cutoff_rate")).alias(
                "earned_premium_try_at_cutoff_rate"
            ),
            "ultimate_loss_ratio",
        )
        .sort("segment", "line", "entity", "accident_year", "currency")
    )


def ibnr_by_valuation(
    scenario: Scenario, size: SizeSpec, world: ClaimWorld, cut_off: int
) -> pl.DataFrame:
    """True IBNR at each quarter end: ultimate of the claims that have occurred minus the
    incurred (paid plus case reserve) of those reported by then. Includes unreported claims
    and the development of reported ones."""
    first_year, last_year = simulation_years(scenario, size)
    claim = np.arange(len(world))
    final = world.ultimate()
    first_month = int(month_index(to_day(date(first_year, 1, 1))))
    month_ends = month_end(np.arange(first_month, int(month_index(cut_off)) + 1))
    dates = [d for d in month_ends if month_index(d) % 3 == 2 or d == cut_off]

    lines = list(scenario.lines)
    currencies = sorted(set(world.c_currency.tolist()))
    n_years = last_year - first_year + 1
    group = (
        np.array([lines.index(x) for x in world.c_line], dtype=np.int64) * len(currencies)
        + np.array([currencies.index(x) for x in world.c_currency], dtype=np.int64)
    ) * n_years + (year_of(world.c_occ) - first_year)
    n_groups = len(lines) * len(currencies) * n_years
    rows = []
    for day in dates:
        occurred = world.c_occ <= day
        state = world.state(claim, np.full(len(world), day))
        count = np.bincount(group[occurred], minlength=n_groups)
        sums = {
            "ultimate": np.bincount(
                group[occurred], weights=final["paid"][occurred], minlength=n_groups
            ),
            "paid": np.bincount(
                group[occurred], weights=state["paid"][occurred], minlength=n_groups
            ),
            "case_reserve": np.bincount(
                group[occurred], weights=state["reserve"][occurred], minlength=n_groups
            ),
        }
        stamp = date.fromisoformat(str(np.datetime64(int(day), "D")))
        for g in np.flatnonzero(count):
            li, rest = divmod(int(g), len(currencies) * n_years)
            ci, yi = divmod(rest, n_years)
            rows.append(
                {
                    "valuation_date": stamp,
                    "segment": scenario.lines[lines[li]].segment,
                    "line": lines[li],
                    "accident_year": first_year + yi,
                    "currency": currencies[ci],
                    **{name: float(values[g]) for name, values in sums.items()},
                }
            )
    return (
        pl.DataFrame(rows)
        .with_columns(
            (pl.col("paid") + pl.col("case_reserve")).alias("incurred"),
            (pl.col("ultimate") - pl.col("paid") - pl.col("case_reserve")).alias("ibnr_true"),
        )
        .select(
            "valuation_date",
            "segment",
            "line",
            "accident_year",
            "currency",
            "ultimate",
            "paid",
            "case_reserve",
            "incurred",
            "ibnr_true",
        )
        .sort("valuation_date", "line", "accident_year", "currency")
    )


def development_pattern(
    scenario: Scenario, size: SizeSpec, world: ClaimWorld, cut_off: int
) -> pl.DataFrame:
    """Share of the inflation-free ultimate that is paid, and incurred, at each year end after
    the start of the accident year (lag 1 is the end of the accident year itself)."""
    first_year, last_year = simulation_years(scenario, size)
    base_amount = np.where(
        world.c_nil[world.p_claim],
        0.0,
        world.c_cost[world.p_claim] * world.p_w * world.c_fx_start[world.p_claim],
    )
    base_paid = Cumulative(world.p_claim, world.p_day, base_amount)
    year = year_of(world.c_occ)
    ultimate_base = np.where(world.c_nil, 0.0, world.c_cost * world.c_fx_start)
    rows = []
    for ay in range(first_year, last_year + 1):
        in_year = np.flatnonzero(year == ay)
        for line in scenario.lines:
            claim = in_year[world.c_line[in_year] == line]
            total = float(ultimate_base[claim].sum())
            if len(claim) == 0 or total == 0:
                continue
            for lag in range(1, MAX_LAG_YEARS + 1):
                day = np.full(len(claim), _year_end(ay + lag - 1))
                paid = base_paid.at(claim, day)[0]
                state = world.state(claim, day)
                reserve_base = (
                    state["reserve"] / world.index_for(claim, day) * world.c_fx_start[claim]
                )
                rows.append(
                    {
                        "line": line,
                        "accident_year": ay,
                        "lag_years": lag,
                        "valuation_date": date(ay + lag - 1, 12, 31),
                        "observed_at_cutoff": bool(day[0] <= cut_off),
                        "paid_share": float(paid.sum()) / total,
                        "incurred_share": float((paid + reserve_base).sum()) / total,
                        "reported_count_share": float((state["status"] != -1).sum()) / len(claim),
                    }
                )
    return pl.DataFrame(rows).sort("line", "accident_year", "lag_years")


def frequency_severity(
    scenario: Scenario, size: SizeSpec, world: ClaimWorld, exposure: pl.DataFrame
) -> pl.DataFrame:
    """Realised and parametric claim frequency and mean severity, per line and accident year."""
    year = year_of(world.c_occ)
    regular = world.c_kind == REGULAR
    claims = pl.DataFrame(
        {
            "line": world.c_line.tolist(),
            "accident_year": year,
            "regular": regular,
            "cat": world.c_kind == 1,
            "shock": world.c_kind == SHOCK,
            "non_nil": ~world.c_nil,
            "base_cost": np.where(world.c_nil, 0.0, world.c_cost * world.c_fx_start),
        }
    )
    summary = claims.group_by("line", "accident_year").agg(
        pl.col("regular").sum().alias("claims_regular"),
        pl.col("cat").sum().alias("claims_catastrophe"),
        pl.col("shock").sum().alias("claims_shock"),
        (pl.col("regular") & pl.col("non_nil")).sum().alias("claims_regular_non_nil"),
        pl.when(pl.col("regular") & pl.col("non_nil"))
        .then(pl.col("base_cost"))
        .otherwise(None)
        .mean()
        .alias("mean_base_severity_try"),
    )
    table = exposure.join(summary, on=["line", "accident_year"], how="left").fill_null(0)
    expected_frequency, expected_severity = [], []
    for row in table.iter_rows(named=True):
        line = scenario.lines[row["line"]]
        yrs = (
            to_day(date(row["accident_year"], 7, 1)) - to_day(scenario.meta.base_date)
        ) / DAYS_PER_YEAR
        expected_frequency.append(
            line.frequency.per_exposure_year * (1 + line.frequency.trend_per_year) ** yrs
        )
        expected_severity.append(_expected_base_severity(line))
    return table.with_columns(
        pl.Series("expected_frequency", expected_frequency),
        (pl.col("claims_regular") / pl.col("exposure_years")).alias("observed_frequency"),
        pl.Series("expected_base_severity_try", expected_severity, dtype=pl.Float64),
    )


def _expected_base_severity(line) -> float | None:
    """Mean cost at base prices of a regular non-nil claim, or None where it is not closed form
    (a cap at the sum insured, or severity tied to the sum insured)."""
    severity = line.severity
    if severity.body.dist == "fixed_share_of_sum_insured" or severity.capped_at_sum_insured:
        return None
    body = mean_of(severity.body)
    if severity.tail is not None:
        tail = severity.tail
        if tail.alpha <= 1:
            return None
        body = (1 - tail.probability) * body + tail.probability * tail.threshold * tail.alpha / (
            tail.alpha - 1
        )
    if line.litigation is not None:
        body *= 1 + line.litigation.probability * (line.litigation.severity_multiplier - 1)
    return float(body)


def inflation_path(scenario: Scenario, market: Market, cut_off: int) -> pl.DataFrame:
    """The true price index, its rates and the claims inflation index of every line, by month."""
    months = np.arange(len(market.cpi)) + market.base_month
    ends = month_end(months)
    yoy = np.full(len(months), np.nan)
    yoy[12:] = market.cpi[12:] / market.cpi[:-12] - 1.0
    columns: dict[str, object] = {
        "month_end": pl.Series("month_end", ends).cast(pl.Int32).cast(pl.Date),
        "observed_in_files": ends <= cut_off,
        "cpi": market.cpi,
        "cpi_monthly_rate": market.cpi_monthly_rate,
        "cpi_year_on_year": yoy,
    }
    for name, line in scenario.lines.items():
        if line.severity.body.dist == "fixed_share_of_sum_insured":
            columns[f"claims_index_{name}"] = np.ones(len(months))
        else:
            columns[f"claims_index_{name}"] = (
                market.cpi
                / market.cpi_base_value
                * (1 + line.severity.superimposed_inflation) ** years_since(ends, market.base_day)
            )
    return pl.DataFrame(columns).with_columns(pl.col("cpi_year_on_year").fill_nan(None))
