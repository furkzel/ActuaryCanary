"""The tier B reserving methods of one group (record 0620), run beside tier A by M04.

MT11 (bootstrap) and MT15 (separation) run on the paid triangle, MT12 (Munich) on paid and
incurred together, MT13 (Benktander) on the triangle of its parameter `measure`, MT14 (tail)
on every triangle where MT02 runs, MT16 (frequency and severity) on the counts and amounts that
`TierBSource` builds, MT22 (back-test, and with it AE02) on the incurred triangle against the
selected ultimates. Every judgement goes through the assumptions register
(`judgement_tier_b`); a method that cannot run keeps its reason and never gives a number.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from actuarycanary.methods.assumptions import DEFAULT_WHO, Assumption
from actuarycanary.methods.back_testing import (
    BackTest,
    back_test,
    chain_ladder_runner,
    premium_runners,
)
from actuarycanary.methods.benktander import Benktander, Prior, benktander
from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson
from actuarycanary.methods.cape_cod import CapeCod
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.diagnostics import Diagnostic
from actuarycanary.methods.frequency_severity import FrequencySeverity, frequency_severity
from actuarycanary.methods.judgement_tier_b import horizons, number, parameters
from actuarycanary.methods.munich import Munich, munich_chain_ladder
from actuarycanary.methods.odp_bootstrap import OdpBootstrap, Process, Scale, odp_bootstrap
from actuarycanary.methods.seeding import generator
from actuarycanary.methods.selection import Selection
from actuarycanary.methods.separation import FutureIndex, Separation, separation
from actuarycanary.methods.tail import TailFit
from actuarycanary.modules.tier_b_inputs import (
    ADJUSTED,
    NOMINAL,
    TierBSource,
    group_triangle,
)
from actuarycanary.structures.triangles import Triangle

MT11, MT12, MT13, MT14, MT15, MT16, MT22 = (
    "MT11", "MT12", "MT13", "MT14", "MT15", "MT16", "MT22"
)  # fmt: skip
INFO = "INFO"
TAIL_DEFAULT = 1.0


@dataclass(frozen=True)
class TierBGroup:
    """The tier B results of one group, each a result or the reason it did not run."""

    bootstrap: OdpBootstrap | Skipped
    munich: Munich | Skipped
    benktander: Benktander | Skipped
    benktander_measure: str
    tails: dict[str, TailFit | Skipped]  # by measure
    separation: Separation | Skipped
    separation_origins: tuple[str, ...]
    frequency_severity: FrequencySeverity | Skipped
    frequency_origins: tuple[str, ...]
    frequency_value_basis: str
    back_test: BackTest | Skipped
    diagnostics: tuple[tuple[str, Diagnostic], ...] = field(default=())  # (measure, item)

    def outcomes(self) -> list[tuple[str, object]]:
        """Every outcome with its method ID, the tail of each triangle counted apart."""
        found: list[tuple[str, object]] = [
            (MT11, self.bootstrap),
            (MT12, self.munich),
            (MT13, self.benktander),
            (MT15, self.separation),
            (MT16, self.frequency_severity),
            (MT22, self.back_test),
        ]
        found += [(MT14, tail_outcome(t)) for t in self.tails.values()]
        return found


def tail_outcome(fit: TailFit | Skipped) -> TailFit | Skipped:
    """The fit, or the reason when the chosen curve could not be fitted."""
    if isinstance(fit, TailFit) and isinstance(fit.chosen, Skipped):
        return fit.chosen
    return fit


def _tail_entry(entries: list[Assumption], tail: float) -> list[Assumption]:
    """The MT11 `tail_factor` entry follows the MT02 tail unless a user set its own."""
    out: list[Assumption] = []
    for e in entries:
        if e.name == "tail_factor" and e.who == DEFAULT_WHO and tail != e.value:
            e = e.model_copy(update={"value": tail, "why": "MT11 default: the tail of MT02"})
        out.append(e)
    return out


def _align(found: Triangle | None, like: Triangle, value: float = 0.0) -> np.ndarray | None:
    """The cumulative amounts of `found` on the grid of `like`; `value` where `found` has no
    cell of an origin (a catastrophe in some years only), NaN where `like` has none."""
    if found is None:
        return np.where(np.isfinite(like.cumulative), value, np.nan)
    out = np.where(np.isfinite(like.cumulative), value, np.nan)
    for k, origin in enumerate(found.origins):
        if origin not in like.origins:
            continue
        row = like.origins.index(origin)
        width = min(found.cumulative.shape[1], out.shape[1])
        out[row, :width] = found.cumulative[k, :width]
        out[row, ~np.isfinite(like.cumulative[row])] = np.nan
    return out


def _skipped(method: str, reason: str) -> Skipped:
    return Skipped(method, reason)


def run_tier_b(
    group: tuple[str, ...],
    triangles: Mapping[str, Triangle],
    chains: Mapping[str, ChainLadder | Skipped],
    fergusons: Mapping[str, BornhuetterFerguson | Skipped],
    capes: Mapping[str, CapeCod | Skipped],
    tails: Mapping[str, TailFit | Skipped | None],
    selection: Selection | Skipped | None,
    premium: np.ndarray | None,
    register: object,
    source: TierBSource,
    seed: int,
    development_months: int,
    selection_measure: str,
) -> tuple[TierBGroup, list[Assumption]]:
    """MT11–MT16 and MT22 for one group; also the entries in force of their parameters."""
    entries: list[Assumption] = []
    notes: list[tuple[str, Diagnostic]] = []

    def scope(measure: str) -> str:
        return "/".join((*group, measure))

    def read(method: str, measure: str) -> dict[str, object]:
        values, used = parameters(method, scope(measure), register)  # type: ignore[arg-type]
        entries.extend(used)
        return dict(values)

    # MT11 on the paid triangle ------------------------------------------------------------
    paid = triangles["paid"]
    values = read(MT11, "paid")
    paid_chain = chains["paid"]
    tail = number(values["tail_factor"])  # type: ignore[arg-type]
    if isinstance(paid_chain, ChainLadder) and not any(
        e.method == MT11 and e.name == "tail_factor" and e.who != DEFAULT_WHO for e in entries
    ):
        tail = paid_chain.tail_factor
        entries[:] = _tail_entry(entries, tail)
    bootstrap = odp_bootstrap(
        paid.cumulative,
        generator(seed, *group),
        n_simulations=int(number(values["n_simulations"])),  # type: ignore[arg-type]
        seed=seed,
        process_distribution=Process(str(values["process_distribution"])),
        scale=Scale(str(values["scale"])),
        tail_factor=tail,
        centre_residuals=bool(values["centre_residuals"]),
    )

    # MT12 on paid and incurred together --------------------------------------------------
    incurred = triangles["incurred"]
    values = read(MT12, "incurred")
    munich = munich_chain_ladder(
        paid.cumulative,
        incurred.cumulative,
        calendar=incurred.calendar,
        min_origins=int(number(values["min_origins"])),  # type: ignore[arg-type]
        ages=incurred.ages,
        origins=incurred.origins,
    )

    # MT13 on the triangle of its parameter ------------------------------------------------
    values = read(MT13, selection_measure)
    measure = str(values["measure"])
    prior = Prior(str(values["prior"]))
    prior_result = (fergusons if prior is Prior.BORNHUETTER_FERGUSON else capes)[measure]
    blend = benktander(
        chains[measure],
        prior_result,
        iterations=int(number(values["iterations"])),  # type: ignore[arg-type]
        prior_source=prior,
        origins=triangles[measure].origins,
    )

    # MT16 on counts, amounts and catastrophe claims apart ---------------------------------
    values = read(MT16, selection_measure)
    severity_measure = str(values["severity_measure"])
    separate = bool(values["separate_catastrophes"])
    basis = str(values["value_basis"])
    if basis == ADJUSTED and not source.indexed:
        basis = NOMINAL
        notes.append(
            ("", Diagnostic(MT16, "NOMINAL_SEVERITY", INFO,
                            "the price index is not loaded: severity is trended at nominal "
                            "prices, not at value-date prices"))
        )  # fmt: skip
    fs_origins: tuple[str, ...] = ()
    counts_set, counts_reason = source.counts(separate)
    counts = group_triangle(counts_set, "reported_count", group)
    regular_set, regular_reason = source.regular(basis, ("paid", "incurred"), separate)
    amounts = group_triangle(regular_set, severity_measure, group)
    fs: FrequencySeverity | Skipped
    if counts is None or amounts is None:
        fs = _skipped(
            MT16,
            counts_reason
            or regular_reason
            or "this group has no non-nil claims for the counts and amounts of MT16",
        )
    elif counts.origins != amounts.origins or counts.ages != amounts.ages:
        fs = _skipped(MT16, "the count and amount triangles of this group have different grids")
    else:
        cat = None
        if separate:
            cat_set, cat_reason = source.catastrophe(basis, (severity_measure,))
            cat = _align(group_triangle(cat_set, severity_measure, group), amounts)
            if cat_reason:
                notes.append(("", Diagnostic(MT16, "NO_CATASTROPHE_TRIANGLE", INFO, cat_reason)))
        fs = frequency_severity(
            counts.cumulative,
            amounts.cumulative,
            exposure=source.exposure(group, counts.origins),
            catastrophes=cat,
            maturity_for_trend=number(values["maturity_for_trend"]),  # type: ignore[arg-type]
            min_trend_origins=int(number(values["min_trend_origins"])),  # type: ignore[arg-type]
            value_basis=basis,
            calendar=amounts.calendar,
            origins=amounts.origins,
        )
        fs_origins = counts.origins

    # MT15 on the regular paid triangle with the counts of MT16 -----------------------------
    values = read(MT15, "paid")
    sep: Separation | Skipped
    sep_origins: tuple[str, ...] = ()
    paid_set, paid_reason = source.regular(NOMINAL, ("paid",), separate)
    regular_paid = group_triangle(paid_set, "paid", group)
    if str(values["claim_counts"]) == "ultimate":
        n: np.ndarray | None = fs.ultimate_counts if isinstance(fs, FrequencySeverity) else None
        n_reason = fs.reason if isinstance(fs, Skipped) else ""
        n_origins = fs_origins
    else:
        n = counts.latest if counts is not None else None
        n_reason = counts_reason or "this group has no reported counts"
        n_origins = counts.origins if counts is not None else ()
    if regular_paid is None or n is None:
        sep = _skipped(
            MT15,
            f"separation needs claim counts per origin: {n_reason or paid_reason or 'none'}",
        )
    elif n_origins != regular_paid.origins:
        sep = _skipped(MT15, "the claim counts and the paid triangle have different origins")
    else:
        rate = values["future_rate"]
        sep = separation(
            regular_paid.incremental,
            n,
            future_index=FutureIndex(str(values["future_index"])),
            rate=None if rate is None else number(rate),  # type: ignore[arg-type]
            trend_periods=int(number(values["trend_periods"])),  # type: ignore[arg-type]
            period_months=development_months,
        )
        sep_origins = regular_paid.origins

    # MT22 on the incurred triangle against the selected ultimates --------------------------
    values = read(MT22, selection_measure)
    chain = chains[selection_measure]
    tri = triangles[selection_measure]
    test: BackTest | Skipped
    if str(values["past_selections"]) != "rerun":
        test = _skipped(
            MT22, "reading the selections of past run manifests is not built; use rerun"
        )
    elif isinstance(selection, Skipped) or selection is None:
        test = _skipped(
            MT22, "there is no selected ultimate to test against: " + (
                selection.reason if isinstance(selection, Skipped) else "the selection did not run"
            )
        )  # fmt: skip
    elif isinstance(chain, Skipped):
        test = _skipped(MT22, f"the chain ladder did not run: {chain.reason}")
    else:
        runners = {"MT02": chain_ladder_runner}
        if premium is not None:
            runners |= premium_runners(premium)
        test = back_test(
            tri.cumulative,
            tri.calendar,
            tri.origins,
            selection.ultimate,
            1 / chain.cdf_at_latest,
            runners=runners,
            horizons_months=horizons(values["horizons_months"]),  # type: ignore[arg-type]
            development_months=development_months,
            mature_at=number(values["mature_at"]),  # type: ignore[arg-type]
            bootstrap_rng=generator(seed, *group, MT22),
            backtest_simulations=int(number(values["backtest_simulations"])),  # type: ignore[arg-type]
        )

    results = TierBGroup(
        bootstrap,
        munich,
        blend,
        measure,
        {m: t for m, t in tails.items() if t is not None},
        sep,
        sep_origins,
        fs,
        fs_origins,
        basis,
        test,
    )
    found = [(m, d) for m, d in notes]
    for item in (bootstrap, munich, blend, fs):
        if not isinstance(item, Skipped):
            found += [(_measure_of(item, measure), d) for d in item.diagnostics]
    for m, fit in results.tails.items():
        if isinstance(fit, TailFit):
            found += [(m, d) for d in fit.diagnostics]
    return (
        TierBGroup(
            results.bootstrap,
            results.munich,
            results.benktander,
            results.benktander_measure,
            results.tails,
            results.separation,
            results.separation_origins,
            results.frequency_severity,
            results.frequency_origins,
            results.frequency_value_basis,
            results.back_test,
            tuple(found),
        ),
        entries,
    )


def _measure_of(item: object, blend_measure: str) -> str:
    """The triangle a result's diagnostics belong to."""
    if isinstance(item, OdpBootstrap | Separation):
        return "paid"
    if isinstance(item, Benktander):
        return blend_measure
    if isinstance(item, FrequencySeverity):
        return "incurred"
    return ""
