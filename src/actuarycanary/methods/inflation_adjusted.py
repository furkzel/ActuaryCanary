"""Inflation-adjusted chain ladder (MT07).

Chain ladder on a paid triangle restated to value-date prices (built by structures on the
INFLATION_ADJUSTED basis, CV02), so the factors are free of past inflation. Future payments
stay at value-date prices unless a future inflation assumption is given; then each is placed
at the middle of its development period and re-inflated (record 0012).

Every origin's latest cell lies at the cut-off (MT01), so the future period s of any origin
runs from s - 1 to s development periods after the cut-off.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from actuarycanary.structures.periods import month_end, month_index

DAYS_PER_YEAR = 365.25
VALUE_DATE_LABEL = "at value-date prices"


@dataclass(frozen=True)
class CashFlow:
    """Expected payments of one future calendar period, both price bases."""

    period: int  # 1 = the first development period after the cut-off
    start: date  # exclusive
    end: date
    payment_date: date  # middle of the period (days rounded down)
    at_value_date_prices: float
    nominal: float | None


@dataclass(frozen=True)
class InflationAdjusted:
    chain: ChainLadder  # MT02 on the adjusted triangle
    adjusted_triangle: np.ndarray
    value_date: date
    future_inflation: float | None
    future: np.ndarray  # adjusted payments per origin and future period s = 1.. (NaN if none)
    years_from_value_date: np.ndarray  # per future period s, at its middle
    nominal_paid: np.ndarray  # P(i, c), nominal paid at the cut-off
    nominal_factors: np.ndarray | None  # MT02 factors on the nominal triangle, if given

    @property
    def ultimate_at_value_date_prices(self) -> np.ndarray:
        return self.chain.ultimate

    @property
    def unpaid_at_value_date_prices(self) -> np.ndarray:
        return np.nansum(self.future, axis=1)

    @property
    def nominal_future(self) -> np.ndarray | None:
        if self.future_inflation is None:
            return None
        growth = (1 + self.future_inflation) ** self.years_from_value_date
        return self.future * growth

    @property
    def nominal_unpaid(self) -> np.ndarray | None:
        nominal = self.nominal_future
        return None if nominal is None else np.nansum(nominal, axis=1)

    @property
    def nominal_ultimate(self) -> np.ndarray | None:
        unpaid = self.nominal_unpaid
        return None if unpaid is None else self.nominal_paid + unpaid

    @property
    def inflation_removed(self) -> np.ndarray | None:
        """Nominal over adjusted development factor per column (diagnostic)."""
        if self.nominal_factors is None:
            return None
        return self.nominal_factors / self.chain.factors


def _future_payments(chain: ChainLadder) -> np.ndarray:
    """Adjusted increments after the latest cell, by future period; the tail (if any) is paid
    in the period after the last development age."""
    n_origins, n_dev = chain.projected.shape
    horizon = n_dev - int(chain.latest_index.min()) - 1 + (chain.tail_factor != 1.0)
    future = np.full((n_origins, max(horizon, 0)), np.nan)
    for i in range(n_origins):
        latest = int(chain.latest_index[i])
        path = list(chain.projected[i, latest:])
        if chain.tail_factor != 1.0:
            path.append(chain.ultimate[i])
        steps = np.diff(path)
        future[i, : len(steps)] = steps
    return future


def cash_flow_periods(
    cut_off: date, development_months: int, horizon: int
) -> list[tuple[date, date]]:
    """(start exclusive, end) of the future development periods s = 1..horizon."""
    c = month_index(cut_off)
    return [
        (month_end(c + (s - 1) * development_months), month_end(c + s * development_months))
        for s in range(1, horizon + 1)
    ]


def inflation_adjusted_chain_ladder(
    adjusted: np.ndarray,
    *,
    nominal_paid: np.ndarray,
    cut_off: date,
    development_months: int,
    value_date: date | None = None,
    future_inflation: float | None = None,
    nominal: np.ndarray | None = None,
    calendar: np.ndarray | None = None,
    average: Average = Average.VOLUME_WEIGHTED,
    n_diagonals: int | None = None,
    exclusions: Iterable[tuple[int, int]] = (),
    exclude_high_low: bool = False,
    tail_factor: float = 1.0,
    min_origins: int = 3,
    selected: Mapping[int, float] | None = None,
) -> InflationAdjusted | Skipped:
    """MT07 on the adjusted cumulative paid triangle; MT02 parameters as for chain ladder.

    `nominal_paid` is paid at the cut-off in nominal terms per origin; `nominal`, the nominal
    cumulative paid triangle, only feeds the factor comparison."""
    options = {
        "average": average,
        "n_diagonals": n_diagonals,
        "exclusions": exclusions,
        "exclude_high_low": exclude_high_low,
        "tail_factor": tail_factor,
        "min_origins": min_origins,
        "calendar": calendar,
    }
    chain = chain_ladder(adjusted, selected=selected, **options)
    if isinstance(chain, Skipped):
        return Skipped("MT07", chain.reason)
    value_date = value_date or cut_off
    future = _future_payments(chain)
    periods = cash_flow_periods(cut_off, development_months, future.shape[1])
    years = np.array(
        [
            ((start - value_date).days + (end - start).days / 2) / DAYS_PER_YEAR
            for start, end in periods
        ]
    )
    nominal_factors = None
    if nominal is not None:
        nominal_chain = chain_ladder(nominal, **options)
        if isinstance(nominal_chain, ChainLadder):
            nominal_factors = nominal_chain.factors
    return InflationAdjusted(
        chain=chain,
        adjusted_triangle=np.asarray(adjusted, dtype=float),
        value_date=value_date,
        future_inflation=future_inflation,
        future=future,
        years_from_value_date=years,
        nominal_paid=np.asarray(nominal_paid, dtype=float),
        nominal_factors=nominal_factors,
    )


def future_cash_flows(
    result: InflationAdjusted, cut_off: date, development_months: int
) -> list[CashFlow]:
    """Expected payments by future calendar period, summed over origins (MT07 output)."""
    nominal = result.nominal_future
    flows: list[CashFlow] = []
    periods = cash_flow_periods(cut_off, development_months, result.future.shape[1])
    for s, (start, end) in enumerate(periods):
        middle = start + timedelta(days=(end - start).days // 2)
        flows.append(
            CashFlow(
                s + 1,
                start,
                end,
                middle,
                float(np.nansum(result.future[:, s])),
                None if nominal is None else float(np.nansum(nominal[:, s])),
            )
        )
    return flows
