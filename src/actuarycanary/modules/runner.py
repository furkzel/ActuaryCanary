"""The module runner: runs modules M01 to M06 whenever their concepts are present and says why
the others did not (blueprint 10, decisions 0014, 0032, 0051).

Whether a module can run comes from the quality report (`ModuleStatus`): a required concept
that is not loaded, or a BLOCKING finding on a field its measures require, makes it "unable",
and the module's own `skip_reason` or the finding is the reason. Otherwise the module runs
every measure of its spec with the default views, and a measure that cannot be computed
gives its reason instead of values. Method outputs come through the port of the measures.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.measures.engine import IMPLEMENTATIONS, METHOD_OUTPUTS, run_measure
from actuarycanary.measures.model import (
    Basis,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    MeasureResult,
)
from actuarycanary.modules.views import DEFAULT_VIEWS
from actuarycanary.quality.model import ModuleStatus, QualityReport
from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.spec.models import MeasureSpec, ModuleSpec
from actuarycanary.structures.periods import Period

BUILT_METHODS = frozenset({"MT01", "MT02"})  # the methods this package runs itself


class ModuleState(StrEnum):
    RAN = "ran"
    LIMITED = "limited"  # ran, but some measures or methods are not available
    SKIPPED = "skipped"  # did not run


@dataclass(frozen=True)
class ModuleOutcome:
    module: str
    title: str
    question: str
    state: ModuleState
    reasons: tuple[str, ...] = ()  # why it did not run, or what is missing
    measures: tuple[MeasureResult, ...] = ()
    methods_built: tuple[str, ...] = ()
    methods_missing: tuple[str, ...] = ()

    @property
    def available(self) -> tuple[MeasureResult, ...]:
        return tuple(m for m in self.measures if m.available)

    @property
    def unavailable(self) -> tuple[MeasureResult, ...]:
        return tuple(m for m in self.measures if not m.available)


@dataclass(frozen=True)
class AnalysisResult:
    """What the module runner produced: one outcome per module, in module order."""

    modules: tuple[ModuleOutcome, ...]
    inputs: MeasureInputs | None = field(default=None, compare=False, repr=False)

    def get(self, module: str) -> ModuleOutcome:
        return next(m for m in self.modules if m.module == module)

    def results(self) -> tuple[MeasureResult, ...]:
        """Every measure result once, in module order (a measure shared by modules appears
        once)."""
        seen: set[tuple[str, MeasureRequest]] = set()
        out: list[MeasureResult] = []
        for module in self.modules:
            for result in module.measures:
                key = (result.measure, result.request)
                if key not in seen:
                    seen.add(key)
                    out.append(result)
        return tuple(out)


def request_for(
    spec: MeasureSpec,
    breakdowns: Sequence[str],
    period: Period,
    reinsurance: ReinsuranceBasis,
    value: ValueBasis,
    view: CurrencyView = CurrencyView.REPORTING,
) -> tuple[MeasureRequest, str]:
    """The request for a default view on the run's bases, or the first basis the spec defines
    when the run's is not among them (and the note that says so). In the ORIGINAL currency
    view a measure is asked in the ORIGINAL view where the spec defines it."""
    allowed = spec.bases
    chosen_reinsurance = (
        reinsurance
        if reinsurance.value in allowed.reinsurance
        else ReinsuranceBasis(allowed.reinsurance[0])
    )
    chosen_value = value if value.value in allowed.value else ValueBasis(allowed.value[0])
    if view is CurrencyView.ORIGINAL and "ORIGINAL" in allowed.currency:
        currency = CurrencyView.ORIGINAL
    else:
        currency = (
            CurrencyView.REPORTING if "REPORTING" in allowed.currency else CurrencyView.ORIGINAL
        )
    note = ""
    if chosen_reinsurance is not reinsurance or chosen_value is not value:
        note = (
            f"{spec.id} is defined on {chosen_reinsurance.value}, {chosen_value.value} only: "
            "shown on that basis"
        )
    basis = Basis(chosen_reinsurance, currency, chosen_value)
    return MeasureRequest(tuple(breakdowns), period, basis), note


def dq01_result(
    catalogue: SpecCatalogue, inputs: MeasureInputs, quality: QualityReport
) -> MeasureResult:
    """DQ01 from the quality report: the overall score, then by concept and by dimension."""
    spec = catalogue.measures["DQ01"]
    rows = [("overall", "all", quality.overall)]
    rows += [("concept", name, score) for name, score in quality.by_concept.items()]
    rows += [("dimension", name, score) for name, score in quality.by_dimension.items()]
    frame = pl.DataFrame(
        {
            "scope": [r[0] for r in rows],
            "name": [r[1] for r in rows],
            "value": [r[2].value for r in rows],
            "rules": [float(r[2].rules) for r in rows],
            "note": [""] * len(rows),
        },
        schema_overrides={"value": pl.Float64},
    )
    return MeasureResult(
        spec.id,
        spec.version,
        spec.title_en,
        spec.unit,
        MeasureRequest(("data_concept",)),
        inputs.reporting_currency,
        frame=frame,
    )


def _status(quality: QualityReport, module: str) -> ModuleStatus | None:
    return next((m for m in quality.modules if m.module == module), None)


def _methods(module: ModuleSpec, inputs: MeasureInputs) -> tuple[tuple[str, ...], tuple[str, ...]]:
    built = BUILT_METHODS | inputs.methods.built()
    return (
        tuple(m for m in module.methods if m in built),
        tuple(m for m in module.methods if m not in built),
    )


def run_module(
    module: ModuleSpec,
    catalogue: SpecCatalogue,
    inputs: MeasureInputs,
    quality: QualityReport,
    period: Period,
    reinsurance: ReinsuranceBasis,
    value: ValueBasis,
    cache: dict[tuple[str, MeasureRequest], MeasureResult],
    notes: Sequence[str] = (),
    view: CurrencyView = CurrencyView.REPORTING,
) -> ModuleOutcome:
    built, missing = _methods(module, inputs)
    status = _status(quality, module.id)
    head = {
        "module": module.id,
        "title": module.title_en,
        "question": module.question,
        "methods_built": built,
        "methods_missing": missing,
    }
    if status is not None and status.status == "unable":
        return ModuleOutcome(state=ModuleState.SKIPPED, reasons=status.reasons, **head)  # type: ignore[arg-type]
    unavailable_by_quality = set(status.unavailable) if status is not None else set()
    results: list[MeasureResult] = []
    for measure_id in module.measures:
        spec = catalogue.measures[measure_id]
        if measure_id == "DQ01":
            results.append(dq01_result(catalogue, inputs, quality))
            continue
        if measure_id in unavailable_by_quality:
            reasons = "; ".join(status.reasons) if status is not None else ""
            results.append(
                MeasureResult(
                    spec.id,
                    spec.version,
                    spec.title_en,
                    spec.unit,
                    MeasureRequest(),
                    inputs.reporting_currency,
                    reason=f"blocked by a data finding: {reasons}",
                )
            )
            continue
        if measure_id not in IMPLEMENTATIONS and measure_id not in METHOD_OUTPUTS:
            continue
        for breakdowns in DEFAULT_VIEWS.get(measure_id, ((),)):
            request, note = request_for(spec, breakdowns, period, reinsurance, value, view)
            key = (measure_id, request)
            if key not in cache:
                result = run_measure(catalogue, inputs, measure_id, request)
                cache[key] = replace(result, notes=(note, *result.notes)) if note else result
            results.append(cache[key])
    reasons = [*_reasons(results, missing, status), *notes]
    # the methods of the module that exist (MT01, MT02) have run in the pipeline already
    if not any(r.available for r in results) and not built:
        return ModuleOutcome(
            state=ModuleState.SKIPPED,
            reasons=("no measure could be computed", *reasons),
            measures=tuple(results),
            **head,  # type: ignore[arg-type]
        )
    limited = bool(reasons) or (status is not None and status.status == "limited")
    return ModuleOutcome(
        state=ModuleState.LIMITED if limited else ModuleState.RAN,
        reasons=tuple(reasons),
        measures=tuple(results),
        **head,  # type: ignore[arg-type]
    )


def _reasons(
    results: Sequence[MeasureResult], missing_methods: Sequence[str], status: ModuleStatus | None
) -> list[str]:
    reasons: list[str] = []
    if status is not None:
        reasons += status.reasons
    by_reason: dict[str, list[str]] = {}
    for result in results:
        if not result.available:
            names = by_reason.setdefault(result.reason, [])
            if result.measure not in names:
                names.append(result.measure)
    reasons += [f"{', '.join(names)}: {reason}" for reason, names in by_reason.items()]
    if missing_methods:
        reasons.append(f"methods not built yet: {', '.join(missing_methods)}")
    return reasons


def run_modules(
    catalogue: SpecCatalogue,
    inputs: MeasureInputs,
    quality: QualityReport,
    period: Period = Period.YEAR,
    reinsurance: ReinsuranceBasis = ReinsuranceBasis.GROSS,
    value: ValueBasis = ValueBasis.NOMINAL,
    only: Mapping[str, object] | None = None,
    cache: dict[tuple[str, MeasureRequest], MeasureResult] | None = None,
    notes: Mapping[str, Sequence[str]] | None = None,
    view: CurrencyView = CurrencyView.REPORTING,
) -> AnalysisResult:
    """Run every module of the catalogue (phase 1) in module order. `cache` holds measures
    already computed; `notes` are what a module's methods report, by module ID: a module with
    a note is limited."""
    cache = {} if cache is None else cache
    notes = notes or {}
    outcomes = [
        run_module(
            module,
            catalogue,
            inputs,
            quality,
            period,
            reinsurance,
            value,
            cache,
            notes.get(module.id, ()),
            view,
        )
        for module in sorted(catalogue.modules.values(), key=lambda m: m.id)
        if only is None or module.id in only
    ]
    return AnalysisResult(tuple(outcomes), inputs)
