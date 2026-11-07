"""Over-dispersed Poisson bootstrap (MT11): the predictive distribution of the chain-ladder
reserve (England and Verrall 1999, 2002).

Pearson residuals of the fitted chain ladder are resampled into pseudo-triangles (parameter
error); the chain ladder is refitted on each and its future increments, projected from the
pseudo-triangle's own latest diagonal (decision 0612), are drawn from the gamma or the
over-dispersed Poisson process (process error, decision 0609). Every draw comes from the
seeded stream it is given (`methods.seeding`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import polars as pl

from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from actuarycanary.methods.diagnostics import WARNING, Diagnostic
from actuarycanary.methods.mack import PERCENTILES, TVAR_LEVEL, VAR_LEVEL, Mack
from actuarycanary.methods.seeding import RUN_SEED

N_SIMULATIONS = 10_000
MIN_ORIGINS = 5
MIN_DEGREES_OF_FREEDOM = 3  # n - p of 2 or less: not run
NEGATIVE_SHARE_WARNING = 0.01
BATCH = 1_000  # simulations per batch, which bounds memory and fixes the order of the draws
HISTOGRAM_BINS = 50


class Process(StrEnum):
    GAMMA = "gamma"
    ODP = "odp"


class Scale(StrEnum):
    CONSTANT = "constant"
    BY_DEVELOPMENT = "by_development"


@dataclass(frozen=True)
class Summary:
    mean: float
    standard_deviation: float
    percentiles: dict[float, float]
    var_level: float
    value_at_risk: float
    tvar_level: float
    tail_value_at_risk: float

    @property
    def coefficient_of_variation(self) -> float:
        return self.standard_deviation / self.mean if self.mean else float("nan")


@dataclass(frozen=True)
class OdpBootstrap:
    chain: ChainLadder  # the fitted model: volume-weighted, all diagonals, tail 1
    fitted: np.ndarray  # fitted incremental means mu(i, j) on observed cells
    incremental: np.ndarray  # observed incremental paid X(i, j)
    unscaled_residuals: np.ndarray  # r(i, j)
    adjusted_residuals: np.ndarray  # r(i, j) sqrt(n / (n - p))
    in_pool: np.ndarray  # bool: the residual is resampled (cells fitted exactly are not)
    pool: np.ndarray  # the residuals resampled, centred when centre_residuals
    scale_parameter: float  # phi
    degrees_of_freedom: int  # n - p
    seed: int
    n_simulations: int
    process: Process
    tail_factor: float
    reserves: np.ndarray  # simulations x origins
    cash_flows: np.ndarray  # simulations x future calendar periods 1, 2, ...
    percentile_levels: tuple[float, ...]
    var_level: float
    tvar_level: float
    diagnostics: tuple[Diagnostic, ...]

    @property
    def total(self) -> np.ndarray:
        return self.reserves.sum(axis=1)

    @property
    def chain_ladder_reserve(self) -> np.ndarray:
        return self.chain.reserve

    @property
    def bias(self) -> float:
        """Mean simulated total reserve over the chain-ladder reserve, minus 1 (diagnostic)."""
        reserve = float(self.chain.reserve.sum())
        return float(self.total.mean()) / reserve - 1 if reserve else float("nan")

    def summarise(self, values: np.ndarray) -> Summary:
        return summary(values, self.percentile_levels, self.var_level, self.tvar_level)

    def summary(self) -> tuple[list[Summary], Summary]:
        """Per origin and in total (MT11 output `summary`)."""
        return [self.summarise(self.reserves[:, i]) for i in range(self.reserves.shape[1])], (
            self.summarise(self.total)
        )

    def cash_flow_summary(self) -> list[Summary]:
        """Mean and percentiles of future payments per calendar period (MT11 output)."""
        return [self.summarise(self.cash_flows[:, s]) for s in range(self.cash_flows.shape[1])]

    def residual_table(self, origins: Sequence[str], ages: Sequence[int]) -> pl.DataFrame:
        """Unscaled and adjusted residuals with origin, development and calendar diagonal."""
        rows = [
            (origins[i], ages[j], int(i + j), float(self.unscaled_residuals[i, j]),
             float(self.adjusted_residuals[i, j]), bool(self.in_pool[i, j]),
             float(self.fitted[i, j]))
            for i, j in zip(*np.nonzero(np.isfinite(self.fitted)), strict=True)
        ]  # fmt: skip
        names = ["origin", "age", "diagonal", "unscaled", "adjusted", "in_pool", "fitted"]
        return pl.DataFrame(rows, schema=names, orient="row")

    def distribution_frame(self, origins: Sequence[str]) -> pl.DataFrame:
        """Simulated reserves per origin and in total, one row per simulation (the parquet file
        of the run folder)."""
        columns = {"simulation": np.arange(self.n_simulations)}
        columns |= {str(o): self.reserves[:, i] for i, o in enumerate(origins)}
        return pl.DataFrame(columns | {"total": self.total})

    def histogram(self, bins: int = HISTOGRAM_BINS) -> tuple[np.ndarray, np.ndarray]:
        """(counts, edges) of the simulated total reserve (diagnostic)."""
        return np.histogram(self.total, bins=bins)

    def against_mack(self, mack: Mack) -> dict[str, float]:
        """Bootstrap total range beside the Mack lognormal range of MT06 (diagnostic)."""
        _, boot = self.summary()
        _, lognormal = mack.ranges(self.percentile_levels, self.var_level, self.tvar_level)
        found = {"bootstrap_mean": boot.mean, "mack_reserve": mack.total_reserve,
                 "bootstrap_sd": boot.standard_deviation,
                 "mack_standard_error": mack.total_standard_error}  # fmt: skip
        for p in self.percentile_levels:
            found[f"bootstrap_p{p:g}"] = boot.percentiles[p]
            found[f"mack_p{p:g}"] = lognormal.percentiles[p] if lognormal else float("nan")
        return found


def summary(
    values: np.ndarray,
    percentiles: Sequence[float] = PERCENTILES,
    var_level: float = VAR_LEVEL,
    tvar_level: float = TVAR_LEVEL,
) -> Summary:
    """Mean, sd, percentiles, VaR and TVaR of simulated values (MT11, as MT06)."""
    values = np.asarray(values, dtype=float)
    threshold = float(np.quantile(values, tvar_level))
    return Summary(
        mean=float(values.mean()),
        standard_deviation=float(values.std(ddof=1)),
        percentiles={p: float(np.quantile(values, p)) for p in percentiles},
        var_level=var_level,
        value_at_risk=float(np.quantile(values, var_level)),
        tvar_level=tvar_level,
        tail_value_at_risk=float(values[values >= threshold].mean()),
    )


def _fitted_increments(chain: ChainLadder, observed: np.ndarray) -> np.ndarray:
    """mu(i, j): cumulative fitted backwards from the latest diagonal, then differenced."""
    n_origins, n_dev = observed.shape
    fitted = np.full((n_origins, n_dev), np.nan)
    for i in range(n_origins):
        last = int(chain.latest_index[i])
        fitted[i, last] = chain.latest[i]
        for j in range(last - 1, -1, -1):
            fitted[i, j] = fitted[i, j + 1] / chain.factors[j]
    increments = fitted.copy()
    increments[:, 1:] = fitted[:, 1:] - fitted[:, :-1]
    return np.where(observed, increments, np.nan)


def _single_cells(observed: np.ndarray) -> np.ndarray:
    """Cells alone in their origin or column: fitted exactly, so their residual is zero."""
    alone_in_row = observed & (observed.sum(axis=1) == 1)[:, None]
    alone_in_column = observed & (observed.sum(axis=0) == 1)[None, :]
    return alone_in_row | alone_in_column


def _refit_and_project(
    pseudo: np.ndarray, observed: np.ndarray, latest_index: np.ndarray, tail_factor: float
) -> tuple[np.ndarray, np.ndarray]:
    """Future incremental means of each pseudo-triangle (batch x origins x columns, NaN on
    observed cells) and the tail amount per origin (batch x origins)."""
    batch, n_origins, n_dev = pseudo.shape
    cumulative = np.cumsum(np.where(observed, pseudo, 0.0), axis=2)
    both = observed[:, 1:] & observed[:, :-1]
    numerator = (cumulative[:, :, 1:] * both).sum(axis=1)
    denominator = (cumulative[:, :, :-1] * both).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        factors = np.where(denominator != 0, numerator / denominator, 1.0)  # batch x columns
    rows = np.arange(n_origins)
    latest = cumulative[:, rows, latest_index]  # batch x origins
    projected = np.empty((batch, n_origins, n_dev))
    projected[:, rows, latest_index] = latest
    for j in range(n_dev - 1):
        later = latest_index <= j
        projected[:, later, j + 1] = projected[:, later, j] * factors[:, j, None]
    future = np.full((batch, n_origins, n_dev), np.nan)
    future[:, :, 1:] = projected[:, :, 1:] - projected[:, :, :-1]
    future[:, observed] = np.nan
    tail = projected[:, :, -1] * (tail_factor - 1)
    return future, tail


def _process(
    rng: np.random.Generator, means: np.ndarray, phi: float, process: Process
) -> np.ndarray:
    """Draws with mean |m| and variance phi |m|, sign restored (MT11, decision 0609)."""
    size = np.abs(means)
    if process is Process.GAMMA:
        draws = rng.gamma(size / phi, phi)
    else:
        draws = phi * rng.poisson(size / phi)
    return draws * np.sign(means)


def odp_bootstrap(
    cumulative: np.ndarray,
    rng: np.random.Generator | None = None,
    *,
    n_simulations: int = N_SIMULATIONS,
    seed: int = RUN_SEED,
    process_distribution: Process = Process.GAMMA,
    scale: Scale = Scale.CONSTANT,
    tail_factor: float = 1.0,
    centre_residuals: bool = True,
    percentiles: Sequence[float] = PERCENTILES,
    var_level: float = VAR_LEVEL,
    tvar_level: float = TVAR_LEVEL,
    min_origins: int = MIN_ORIGINS,
) -> OdpBootstrap | Skipped:
    """MT11 on a cumulative paid triangle whose latest diagonal is the cut-off (NaN after it).

    `rng` is the stream of this group (`seeding.generator(seed, *group)`); without one the
    stream is `default_rng(seed)`. `seed` is recorded in the result either way."""
    cumulative = np.asarray(cumulative, dtype=float)
    if Scale(scale) is Scale.BY_DEVELOPMENT:
        return Skipped(
            "MT11",
            "the scale option by_development is not built: the spec gives no formula for the "
            "per-column scale and the rescaling of residuals (decision 0282)",
        )
    if n_simulations < 2:
        raise ValueError(f"the bootstrap needs at least 2 simulations, not {n_simulations}")
    n_origins, n_dev = cumulative.shape
    chain = chain_ladder(cumulative, average=Average.VOLUME_WEIGHTED)
    if isinstance(chain, Skipped) or n_origins < min_origins:
        return Skipped(
            "MT11", f"the bootstrap needs a chain ladder on at least {min_origins} origin periods"
        )
    observed = ~np.isnan(cumulative)
    incremental = cumulative.copy()
    incremental[:, 1:] = cumulative[:, 1:] - cumulative[:, :-1]
    incremental = np.where(observed, incremental, np.nan)
    for j in range(n_dev):
        if not np.nansum(incremental[:, j]) > 0:
            return Skipped(
                "MT11", f"incremental paid of development column {j} sums to zero or less"
            )
    fitted = _fitted_increments(chain, observed)
    bad = observed & ~(fitted > 0)
    if bad.any():
        column = int(np.nonzero(bad)[1].min())
        return Skipped("MT11", f"a fitted increment of development column {column} is not positive")

    n_cells = int(observed.sum())
    dof = n_cells - (n_origins + n_dev - 1)
    if dof < MIN_DEGREES_OF_FREEDOM:
        return Skipped("MT11", "too few cells to estimate the scale parameter")
    unscaled = np.where(observed, (incremental - fitted) / np.sqrt(fitted), np.nan)
    phi = float(np.nansum(unscaled**2)) / dof
    adjusted = unscaled * np.sqrt(n_cells / dof)
    in_pool = observed & ~_single_cells(observed)
    pool = adjusted[in_pool]
    if centre_residuals:
        pool = pool - pool.mean()

    rng = rng if rng is not None else np.random.default_rng(seed)
    latest_index = chain.latest_index
    # future period of cell (i, k) after the cut-off: k - J(i); the tail falls after the last age
    periods = np.arange(n_dev)[None, :] - latest_index[:, None]
    n_periods = int(periods.max()) + (1 if tail_factor != 1 else 0)
    reserves = np.empty((n_simulations, n_origins))
    cash_flows = np.zeros((n_simulations, max(n_periods, 0)))
    mu = fitted[observed]
    root = np.sqrt(mu)
    process = Process(process_distribution)
    for start in range(0, n_simulations, BATCH):
        size = min(BATCH, n_simulations - start)
        draws = pool[rng.integers(0, len(pool), size=(size, n_cells))]
        pseudo = np.zeros((size, n_origins, n_dev))
        pseudo[:, observed] = mu + draws * root
        means, tail = _refit_and_project(pseudo, observed, latest_index, tail_factor)
        future = ~observed
        sampled = np.zeros_like(means)
        sampled[:, future] = _process(rng, means[:, future], phi, process)
        reserves[start : start + size] = sampled.sum(axis=2) + tail
        for s in range(1, int(periods.max()) + 1):
            cash_flows[start : start + size, s - 1] = sampled[:, periods == s].sum(axis=1)
        if tail_factor != 1:  # origin i's tail is paid in period n_dev - J(i)
            for i in range(n_origins):
                cash_flows[start : start + size, n_dev - 1 - latest_index[i]] += tail[:, i]

    diagnostics: list[Diagnostic] = []
    negative = float((reserves.sum(axis=1) < 0).mean())
    if negative > NEGATIVE_SHARE_WARNING:
        diagnostics.append(
            Diagnostic(
                "MT11",
                "NEGATIVE_TOTAL_RESERVE",
                WARNING,
                f"{negative:.1%} of the simulations have a negative total reserve (more than "
                f"{NEGATIVE_SHARE_WARNING:.0%})",
                value=negative,
            )
        )
    return OdpBootstrap(
        chain=chain,
        fitted=fitted,
        incremental=incremental,
        unscaled_residuals=unscaled,
        adjusted_residuals=adjusted,
        in_pool=in_pool,
        pool=pool,
        scale_parameter=phi,
        degrees_of_freedom=dof,
        seed=seed,
        n_simulations=n_simulations,
        process=process,
        tail_factor=tail_factor,
        reserves=reserves,
        cash_flows=cash_flows,
        percentile_levels=tuple(percentiles),
        var_level=var_level,
        tvar_level=tvar_level,
        diagnostics=tuple(diagnostics),
    )
