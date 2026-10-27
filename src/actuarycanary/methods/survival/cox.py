"""Cox proportional hazards by partial likelihood (MT19), numpy and scipy only (record 0600).

h(t | x) = h0(t) exp(beta'x). Tied event times are handled by the rule of the parameter: Efron
(each tied event takes its share of the tied events out of the risk set) or Breslow (every tied
event sees the whole risk set). The log partial likelihood, its gradient and its Hessian are
exact; the maximum is found with scipy's trust-region Newton method. Standard errors come from
the inverse of the information matrix, the overall tests are Wald and likelihood ratio, and the
baseline cumulative hazard is the Breslow estimate.

Concordance and the Schoenfeld-residual test are computed here too; they are information until
an external reference is frozen (decision 0616).
"""

import math
from dataclasses import dataclass

import numpy as np
from scipy import optimize, stats

from actuarycanary.methods.chain_ladder import Skipped

METHOD = "MT19"
EFRON, BRESLOW = "efron", "breslow"
TIES = (EFRON, BRESLOW)
CONFIDENCE = 0.95
GRADIENT_TOLERANCE = 1e-9
DECREMENT_TOLERANCE = 1e-8  # gradient' (information)^-1 gradient at the solution
NEWTON_POLISH = 3
MAX_ITERATIONS = 200
DIVERGED = 20.0  # a coefficient beyond this (a hazard ratio of 5e8) means no finite maximum
MAX_LEVELS_FOR_PAIR_COUNTS = 400


@dataclass(frozen=True)
class _Data:
    """The observations sorted by time, with the bookkeeping of the event times."""

    x: np.ndarray  # n x p, sorted by time
    event_rows: np.ndarray  # positions (in the sorted order) of the events
    group: np.ndarray  # per event: index of its event time
    risk_start: np.ndarray  # per event time: first position of its risk set
    group_start: np.ndarray  # per event time: first event index of its events
    sizes: np.ndarray  # per event time: number of events d
    share: np.ndarray  # per event: r / d for Efron, 0 for Breslow
    times: np.ndarray  # distinct event times


def _prepare(
    time: np.ndarray, event: np.ndarray, x: np.ndarray, ties: str
) -> tuple[_Data, np.ndarray]:
    order = np.argsort(time, kind="stable")
    t, e, xs = time[order], event[order], x[order]
    event_rows = np.flatnonzero(e)
    times, group_start, sizes = np.unique(t[event_rows], return_index=True, return_counts=True)
    group = np.repeat(np.arange(len(times)), sizes)
    rank = np.arange(len(event_rows)) - np.repeat(group_start, sizes)
    share = rank / np.repeat(sizes, sizes) if ties == EFRON else np.zeros(len(event_rows))
    risk_start = np.searchsorted(t, times, side="left")
    return _Data(xs, event_rows, group, risk_start, group_start, sizes, share, times), order


def _suffix(values: np.ndarray, start: np.ndarray) -> np.ndarray:
    """Sums of `values` (rows) from each position of `start` to the end."""
    return np.cumsum(values[::-1], axis=0)[::-1][start]


def _sums(data: _Data, eta: np.ndarray, with_second: bool):
    """Risk-set sums S0, S1, S2 and tied-event sums T0, T1, T2 per event time, for weights
    exp(eta - max eta). Returns the shift as well."""
    shift = float(eta.max()) if eta.size else 0.0
    w = np.exp(eta - shift)
    x = data.x
    p = x.shape[1]
    wx = w[:, None] * x
    s0 = _suffix(w, data.risk_start)
    s1 = _suffix(wx, data.risk_start)
    rows = data.event_rows
    t0 = np.add.reduceat(w[rows], data.group_start)
    t1 = np.add.reduceat(wx[rows], data.group_start, axis=0)
    s2 = t2 = None
    if with_second:
        s2 = np.empty((len(s0), p, p))
        t2 = np.empty((len(s0), p, p))
        for i in range(p):
            block = wx[:, i : i + 1] * x
            s2[:, i, :] = _suffix(block, data.risk_start)
            t2[:, i, :] = np.add.reduceat(block[rows], data.group_start, axis=0)
    return shift, s0, s1, s2, t0, t1, t2


def _partial(beta: np.ndarray, data: _Data) -> tuple[float, np.ndarray, np.ndarray]:
    """(log partial likelihood, gradient, information matrix) at beta."""
    loglik, gradient, information = _evaluate(beta, data, second=True)
    assert information is not None
    return loglik, gradient, information


def _loglik_and_gradient(beta: np.ndarray, data: _Data) -> tuple[float, np.ndarray]:
    loglik, gradient, _ = _evaluate(beta, data, second=False)
    return loglik, gradient


def _evaluate(
    beta: np.ndarray, data: _Data, second: bool
) -> tuple[float, np.ndarray, np.ndarray | None]:
    eta = data.x @ beta
    shift, s0, s1, s2, t0, t1, t2 = _sums(data, eta, second)
    g = data.group
    a0 = s0[g] - data.share * t0[g]
    a1 = s1[g] - data.share[:, None] * t1[g]
    ratio = a1 / a0[:, None]
    loglik = float(eta[data.event_rows].sum() - np.log(a0).sum() - shift * len(a0))
    gradient = data.x[data.event_rows].sum(axis=0) - ratio.sum(axis=0)
    if not second:
        return loglik, gradient, None
    assert s2 is not None and t2 is not None
    m = len(s0)
    inverse = np.bincount(g, weights=1.0 / a0, minlength=m)
    shared = np.bincount(g, weights=data.share / a0, minlength=m)
    information = (
        np.einsum("m,mij->ij", inverse, s2) - np.einsum("m,mij->ij", shared, t2) - ratio.T @ ratio
    )
    return loglik, gradient, information


def loglik_at(
    time: np.ndarray, event: np.ndarray, x: np.ndarray, beta: np.ndarray, ties: str = EFRON
) -> float:
    """The log partial likelihood at a given beta."""
    data, _ = _prepare(
        np.asarray(time, dtype=np.float64), np.asarray(event, dtype=bool),
        np.asarray(x, dtype=np.float64).reshape(len(time), -1), ties,
    )  # fmt: skip
    return _loglik_and_gradient(np.asarray(beta, dtype=np.float64), data)[0]


@dataclass(frozen=True)
class CoxFit:
    names: tuple[str, ...]
    ties: str
    coefficient: np.ndarray
    standard_error: np.ndarray
    covariance: np.ndarray
    z: np.ndarray
    p_value: np.ndarray
    hazard_ratio: np.ndarray
    hazard_ratio_lower: np.ndarray
    hazard_ratio_upper: np.ndarray
    loglik_null: float
    loglik: float
    likelihood_ratio: float
    wald: float
    df: int
    likelihood_ratio_p: float
    wald_p: float
    concordance: float
    iterations: int
    n: int
    n_events: int
    confidence: float
    # kept for the baseline and the residual test
    time: np.ndarray
    event: np.ndarray
    x: np.ndarray


def cox_fit(
    time: np.ndarray,
    event: np.ndarray,
    x: np.ndarray,
    names: tuple[str, ...],
    *,
    ties: str = EFRON,
    confidence: float = CONFIDENCE,
) -> CoxFit | Skipped:
    """Fit the model. `x` is n x p with one column per name. Returns Skipped, with the reason,
    when the likelihood has no usable maximum (no events, a singular information matrix, a
    coefficient running away, no convergence)."""
    if ties not in TIES:
        raise ValueError(f"ties {ties!r}: allowed {', '.join(TIES)}")
    t = np.asarray(time, dtype=np.float64)
    e = np.asarray(event, dtype=bool)
    xs = np.asarray(x, dtype=np.float64).reshape(len(t), -1)
    p = xs.shape[1]
    if p != len(names):
        raise ValueError("one name for every column of x")
    n_events = int(e.sum())
    if n_events == 0:
        return Skipped(METHOD, "no events")
    if p == 0:
        return Skipped(METHOD, "no covariate")
    data, _ = _prepare(t, e, xs, ties)
    null = _loglik_and_gradient(np.zeros(p), data)[0]
    cache: dict[bytes, tuple[float, np.ndarray, np.ndarray]] = {}

    def evaluate(beta: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
        key = beta.tobytes()
        if key not in cache:
            cache.clear()
            cache[key] = _partial(beta, data)
        return cache[key]

    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            result = optimize.minimize(
                lambda b: -evaluate(b)[0],
                np.zeros(p),
                jac=lambda b: -evaluate(b)[1],
                hess=lambda b: evaluate(b)[2],
                method="trust-exact",
                options={"gtol": GRADIENT_TOLERANCE, "maxiter": MAX_ITERATIONS},
            )
    except (FloatingPointError, np.linalg.LinAlgError, ValueError):
        return Skipped(METHOD, "the partial likelihood could not be evaluated: no maximum found")
    beta = result.x
    loglik, gradient, information = evaluate(beta)
    for _ in range(NEWTON_POLISH):  # the optimiser stops at rounding level; finish with Newton
        try:
            step = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            break
        trial_loglik, trial_gradient, trial_information = _partial(beta + step, data)
        if not trial_loglik >= loglik:
            break
        beta, loglik, gradient, information = (
            beta + step,
            trial_loglik,
            trial_gradient,
            trial_information,
        )
    if not np.all(np.isfinite(beta)) or float(np.max(np.abs(beta))) > DIVERGED:
        return Skipped(
            METHOD,
            "a coefficient grows without bound: a level separates the events "
            "(the likelihood has no finite maximum)",
        )
    try:
        decrement = float(gradient @ np.linalg.solve(information, gradient))
    except np.linalg.LinAlgError:
        decrement = math.inf
    if not decrement <= DECREMENT_TOLERANCE:
        return Skipped(METHOD, f"the optimiser did not converge in {result.nit} iterations")
    try:
        covariance = np.linalg.inv(information)
        if not np.all(np.isfinite(covariance)) or np.any(np.diag(covariance) <= 0):
            raise np.linalg.LinAlgError
    except np.linalg.LinAlgError:
        return Skipped(METHOD, "the information matrix is singular: covariates are collinear")
    se = np.sqrt(np.diag(covariance))
    z = beta / se
    p_value = 2.0 * stats.norm.sf(np.abs(z))
    half = stats.norm.ppf(0.5 + confidence / 2.0) * se
    lr = 2.0 * (loglik - null)
    wald = float(beta @ information @ beta)
    return CoxFit(
        names=tuple(names),
        ties=ties,
        coefficient=beta,
        standard_error=se,
        covariance=covariance,
        z=z,
        p_value=p_value,
        hazard_ratio=np.exp(beta),
        hazard_ratio_lower=np.exp(beta - half),
        hazard_ratio_upper=np.exp(beta + half),
        loglik_null=null,
        loglik=loglik,
        likelihood_ratio=lr,
        wald=wald,
        df=p,
        likelihood_ratio_p=float(stats.chi2.sf(lr, p)),
        wald_p=float(stats.chi2.sf(wald, p)),
        concordance=concordance(t, e, xs @ beta),
        iterations=int(result.nit),
        n=len(t),
        n_events=n_events,
        confidence=confidence,
        time=t,
        event=e,
        x=xs,
    )


def breslow_baseline(
    time: np.ndarray, event: np.ndarray, x: np.ndarray, beta: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Breslow estimate of the cumulative baseline hazard (all covariates zero) at the
    distinct event times: the running sum of d over the risk-set sum of exp(beta'x). With
    beta = 0 this is the Nelson-Aalen estimate, the sum of d / n."""
    t = np.asarray(time, dtype=np.float64)
    xs = np.asarray(x, dtype=np.float64).reshape(len(t), -1)
    data, _ = _prepare(t, np.asarray(event, dtype=bool), xs, EFRON)
    eta = data.x @ np.asarray(beta, dtype=np.float64)
    shift = float(eta.max())
    s0 = _suffix(np.exp(eta - shift), data.risk_start)
    increments = data.sizes * np.exp(-shift) / s0
    return data.times, np.cumsum(increments)


def baseline_hazard(fit: CoxFit) -> tuple[np.ndarray, np.ndarray]:
    """The Breslow baseline of a fitted model."""
    return breslow_baseline(fit.time, fit.event, fit.x, fit.coefficient)


def concordance(time: np.ndarray, event: np.ndarray, risk_score: np.ndarray) -> float:
    """Harrell's C: among the pairs in which the shorter observation is an event (a censoring
    at the same time counts as later), the share in which that claim has the higher risk score;
    equal scores count one half; pairs of events at the same time are left out."""
    t = np.asarray(time, dtype=np.float64)
    e = np.asarray(event, dtype=bool)
    score = np.round(np.asarray(risk_score, dtype=np.float64), 12)
    levels, code = np.unique(score, return_inverse=True)
    k = len(levels)
    if k > MAX_LEVELS_FOR_PAIR_COUNTS:
        return _concordance_pairs(t, e, score)
    order = np.lexsort(((~e).astype(int), t))  # events before censorings at the same time
    ts, es, cs = t[order], e[order], code[order]
    n = len(ts)
    events = np.flatnonzero(es)
    if events.size == 0:
        return math.nan
    last_event = np.searchsorted(ts[events], ts[events], side="right") - 1
    first_later = events[last_event] + 1  # after the events of its own time
    onehot = np.zeros((k, n + 1))
    onehot[cs, np.arange(n)] = 1.0
    suffix = np.cumsum(onehot[:, ::-1], axis=1)[:, ::-1]  # level g at positions >= i
    concordant = discordant = tied = 0.0
    for g in range(k):
        later = suffix[g, first_later]
        concordant += float(np.sum((cs[events] > g) * later))
        discordant += float(np.sum((cs[events] < g) * later))
        tied += float(np.sum((cs[events] == g) * later))
    total = concordant + discordant + tied
    return (concordant + 0.5 * tied) / total if total else math.nan


def _concordance_pairs(t: np.ndarray, e: np.ndarray, score: np.ndarray) -> float:
    concordant = discordant = tied = 0.0
    for i in np.flatnonzero(e):
        later = (t > t[i]) | ((t == t[i]) & ~e)
        concordant += float(np.sum(score[i] > score[later]))
        discordant += float(np.sum(score[i] < score[later]))
        tied += float(np.sum(score[i] == score[later]))
    total = concordant + discordant + tied
    return (concordant + 0.5 * tied) / total if total else math.nan


@dataclass(frozen=True)
class ProportionalHazardsTest:
    names: tuple[str, ...]
    statistic: np.ndarray  # per covariate, 1 degree of freedom
    p_value: np.ndarray
    global_statistic: float
    global_df: int
    global_p_value: float
    time: np.ndarray  # transformed time of each event, in event order
    event_time: np.ndarray  # the event times in the unit of the fit
    scaled_residuals: np.ndarray  # events x covariates


def proportional_hazards_test(fit: CoxFit) -> ProportionalHazardsTest:
    """The Grambsch-Therneau test: scaled Schoenfeld residuals against g(t) = one minus the
    Kaplan-Meier estimate just before t (the default of R's cox.zph). Per covariate
    d (sum (g - gbar)(V r)_j)^2 / (V_jj sum (g - gbar)^2) and globally d u'Vu / sum (g - gbar)^2
    with u = sum (g - gbar) r, d the number of events and V the covariance of the coefficients.
    Information until a reference is frozen (decision 0616)."""
    data, order = _prepare(fit.time, fit.event, fit.x, fit.ties)
    eta = data.x @ fit.coefficient
    _, s0, s1, _, t0, t1, _ = _sums(data, eta, with_second=False)
    g = data.group
    a0 = s0[g] - data.share * t0[g]
    a1 = s1[g] - data.share[:, None] * t1[g]
    residuals = data.x[data.event_rows] - a1 / a0[:, None]  # Schoenfeld residuals
    d = len(residuals)
    event_time = fit.time[order][data.event_rows]
    km_times, events = np.unique(event_time, return_counts=True)
    at_risk = len(fit.time) - np.searchsorted(np.sort(fit.time), km_times, side="left")
    survival = np.cumprod(1.0 - events / at_risk)
    before = np.concatenate([[1.0], survival[:-1]])
    transformed = 1.0 - before[np.searchsorted(km_times, event_time)]
    centred = transformed - transformed.mean()
    spread = float(np.sum(centred**2))
    v = fit.covariance
    scaled = fit.coefficient + d * (residuals @ v)
    if spread <= 0.0:
        nan = np.full(len(fit.names), math.nan)
        return ProportionalHazardsTest(
            fit.names, nan, nan, math.nan, len(fit.names), math.nan, transformed, event_time, scaled
        )
    with np.errstate(invalid="ignore"):
        numerator = (centred @ (residuals @ v)) ** 2
        statistic = d * numerator / (np.diag(v) * spread)
        u = centred @ residuals
        global_statistic = float(d * u @ v @ u / spread)
    p = len(fit.names)
    return ProportionalHazardsTest(
        names=fit.names,
        statistic=statistic,
        p_value=stats.chi2.sf(statistic, 1),
        global_statistic=global_statistic,
        global_df=p,
        global_p_value=float(stats.chi2.sf(global_statistic, p)),
        time=transformed,
        event_time=event_time,
        scaled_residuals=scaled,
    )
