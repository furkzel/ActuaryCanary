"""The measure engine: reads a measure's specification, checks the request against it and runs
the function that implements it (blueprint 8, decision 0050).

A request is refused, with the reason, when it names a breakdown or a basis the spec does not
define, when the spec's required fields are not loaded, or when the measure's own edge case
says the value does not exist. Nothing is computed with a field that is not there, and nothing
is set equal to gross, zero or a default to make a value appear (CV03).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import polars as pl

from actuarycanary.convert.bases import BasisUnavailableError
from actuarycanary.convert.market import ConversionError
from actuarycanary.measures import (
    claim_amounts,
    claim_counts,
    expense_measures,
    premium_measures,
    ratio_measures,
    reinsurance_measures,
)
from actuarycanary.measures.claim_base import with_dimensions
from actuarycanary.measures.model import (
    NOTE,
    REF,
    REFS_PREFIX,
    VALUE,
    Computed,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    MeasureResult,
    Missing,
)
from actuarycanary.measures.port import NotAvailable
from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.premium import PremiumError

MeasureFunction = Callable[[MeasureSpec, MeasureInputs, MeasureRequest], Computed | Missing]


@dataclass(frozen=True)
class Implementation:
    function: MeasureFunction
    # breakdowns the spec allows but this version does not build, with the reason
    not_built: Mapping[str, str] = field(default_factory=dict)
    # the reason to give when one required field is missing, if the spec names one
    missing: Mapping[str, str] = field(default_factory=dict)


_TRIANGLES = "it is a view of the triangles, which are built by segment and line (MT01)"
_DEVELOPMENT = "development periods are the columns of the triangles (MT01)"

IMPLEMENTATIONS: dict[str, Implementation] = {
    "PR01": Implementation(premium_measures.written_premium),
    "PR02": Implementation(premium_measures.earned_premium_measure),
    "PR03": Implementation(premium_measures.unearned_premium_measure),
    "PR04": Implementation(premium_measures.cancellation_rate),
    "PR05": Implementation(premium_measures.retention_ratio),
    "PR06": Implementation(premium_measures.average_premium),
    "CL01": Implementation(claim_amounts.paid, {"development_period": _DEVELOPMENT}),
    "CL02": Implementation(claim_amounts.case_reserve, {"development_period": _DEVELOPMENT}),
    "CL03": Implementation(claim_amounts.incurred, {"development_period": _DEVELOPMENT}),
    "CL04": Implementation(claim_counts.claim_counts),
    "CL05": Implementation(claim_counts.frequency),
    "CL06": Implementation(claim_amounts.severity),
    "CL07": Implementation(claim_counts.reporting_delay),
    "CL08": Implementation(claim_counts.settlement_time),
    "CL09": Implementation(claim_counts.settlement_rate),
    "CL10": Implementation(claim_amounts.paid_to_incurred, {"entity": _TRIANGLES}),
    "CL11": Implementation(claim_amounts.case_reserve_run_off),
    "CL12": Implementation(claim_amounts.large_loss_share),
    "RC01": Implementation(
        claim_amounts.subrogation_ratio,
        missing={
            "claim_valuations.subrogation_to_date": "no subrogation column in claim_valuations"
        },
    ),
    "RC02": Implementation(
        claim_amounts.salvage_ratio,
        missing={"claim_valuations.salvage_to_date": "no salvage column in claim_valuations"},
    ),
    "RI01": Implementation(reinsurance_measures.cession_ratio),
    "RI02": Implementation(reinsurance_measures.reinsurance_result),
    "EX01": Implementation(expense_measures.commission_ratio),
    "EX02": Implementation(expense_measures.expense_ratio),
    "EX03": Implementation(expense_measures.claims_handling_ratio),
    "RT01": Implementation(ratio_measures.loss_ratio),
    "RT02": Implementation(ratio_measures.combined_ratio),
    "AE01": Implementation(ratio_measures.actual_versus_expected, {"entity": _TRIANGLES}),
}
METHOD_OUTPUTS = ("RS01", "RS02", "RS03", "AE02")  # tables of the methods, through the port
CURRENCY_VIEWS = {CurrencyView.ORIGINAL: "ORIGINAL", CurrencyView.REPORTING: "REPORTING"}


def implemented() -> tuple[str, ...]:
    return tuple(sorted(IMPLEMENTATIONS))


def _unavailable(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest, reason: str
) -> MeasureResult:
    return MeasureResult(
        spec.id,
        spec.version,
        spec.title_en,
        spec.unit,
        request,
        inputs.reporting_currency,
        reason=reason,
    )


def _missing_requirements(
    spec: MeasureSpec, inputs: MeasureInputs, implementation: Implementation | None
) -> str:
    """The reason the spec's required fields are not all loaded, or an empty string."""
    reasons: list[str] = []
    gone: dict[str, list[str]] = {}
    for reference in spec.requires:
        concept, name = reference.split(".", 1)
        if inputs.has(concept, name):
            continue
        if implementation is not None and reference in implementation.missing:
            reasons.append(implementation.missing[reference])
        elif not inputs.has(concept):
            gone.setdefault(concept, [])
        else:
            gone.setdefault(concept, []).append(name)
    for concept, names in gone.items():
        reasons.append(
            f"{concept} is not loaded"
            if not names
            else f"{concept} has no {', '.join(names)} column"
        )
    return "; ".join(dict.fromkeys(reasons))


def check_request(
    spec: MeasureSpec, request: MeasureRequest, implementation: Implementation | None = None
) -> str:
    """Why the request cannot be answered by this spec, or an empty string."""
    not_defined = [d for d in request.breakdowns if d not in spec.breakdowns]
    if not_defined:
        return (
            f"{spec.id} has no breakdown by {', '.join(not_defined)}; "
            f"its breakdowns are {', '.join(spec.breakdowns)}"
        )
    if implementation is not None:
        for dim in request.breakdowns:
            if dim in implementation.not_built:
                return f"breakdown by {dim} is not built: {implementation.not_built[dim]}"
    bases = spec.bases
    if request.basis.reinsurance.value not in bases.reinsurance:
        return (
            f"{spec.id} is not defined on the {request.basis.reinsurance.value} basis; "
            f"its bases are {', '.join(bases.reinsurance)}"
        )
    # a spec defined in ORIGINAL only counts claims or measures time: its currency view is moot
    moot = set(bases.currency) == {"ORIGINAL"}
    if (
        not moot
        and CURRENCY_VIEWS[request.basis.currency] not in bases.currency
        and not (
            request.basis.currency is CurrencyView.REPORTING and "FUNCTIONAL" in bases.currency
        )
    ):
        return f"{spec.id} is not defined in the {request.basis.currency.value} currency view"
    if request.basis.value.value not in bases.value:
        return f"{spec.id} is not defined on the {request.basis.value.value} value basis"
    return ""


VALUATIONS = "claim_valuations"


def method_refs(
    inputs: MeasureInputs, request: MeasureRequest, table: pl.DataFrame
) -> tuple[pl.DataFrame, tuple[str, ...]]:
    """Lineage of a method output (decision 0071): the claim_valuations rows up to the cut-off
    of the claims of its segment, line and origin period; a row without an origin period (a
    development column, a total) gets the rows of its whole segment and line, because the
    development factors of a line rest on all its origins."""
    feed = inputs.feeds.get(VALUATIONS)
    keys = ["segment", "line"]
    if feed is None or table.height == 0 or not set(keys) <= set(table.columns):
        return table, ()
    column = REFS_PREFIX + VALUATIONS
    rows = feed.filter(pl.col("valuation_date") <= inputs.cut_off).select("claim_id", REF)
    rows, _ = with_dimensions(rows, (*keys, "origin_period"), inputs, request)
    rows = rows.with_columns(pl.col("origin_period").cast(pl.String))
    by_group = rows.group_by(keys).agg(pl.col(REF).sort().alias("_group_refs"))
    out = table.join(by_group, on=keys, how="left")
    if "origin_period" in table.columns:
        by_origin = rows.group_by([*keys, "origin_period"]).agg(pl.col(REF).sort().alias(column))
        out = out.with_columns(pl.col("origin_period").cast(pl.String).alias("_origin")).join(
            by_origin.rename({"origin_period": "_origin"}), on=[*keys, "_origin"], how="left"
        )
        out = out.with_columns(pl.coalesce(column, "_group_refs").alias(column)).drop("_origin")
    else:
        out = out.with_columns(pl.col("_group_refs").alias(column))
    return out.drop("_group_refs"), (VALUATIONS,)


def run_measure(
    catalogue: SpecCatalogue, inputs: MeasureInputs, measure_id: str, request: MeasureRequest
) -> MeasureResult:
    """One measure for one request: values, or the reason there are none."""
    spec = catalogue.measures[measure_id]
    if measure_id in METHOD_OUTPUTS:
        table = inputs.methods.measure(measure_id, request.basis.label())
        if isinstance(table, NotAvailable):
            return _unavailable(spec, inputs, request, table.reason)
        table, concepts = method_refs(inputs, request, table)
        return MeasureResult(
            spec.id,
            spec.version,
            spec.title_en,
            spec.unit,
            request,
            inputs.reporting_currency,
            frame=table,
            concepts=concepts,
        )
    implementation = IMPLEMENTATIONS.get(measure_id)
    if implementation is None:
        return _unavailable(spec, inputs, request, f"{measure_id} is computed elsewhere")
    refusal = check_request(spec, request, implementation)
    if refusal:
        return _unavailable(spec, inputs, request, refusal)
    lacking = _missing_requirements(spec, inputs, implementation)
    if lacking:
        return _unavailable(spec, inputs, request, lacking)
    try:
        outcome = implementation.function(spec, inputs, request)
    except (BasisUnavailableError, ConversionError, PremiumError) as error:
        return _unavailable(spec, inputs, request, str(error))
    if isinstance(outcome, Missing):
        return _unavailable(spec, inputs, request, outcome.reason)
    frame = outcome.frame
    if NOTE not in frame.columns:
        frame = frame.with_columns(pl.lit("").alias(NOTE))
    if VALUE not in frame.columns:
        raise ValueError(f"{measure_id} returned no {VALUE} column")
    return MeasureResult(
        spec.id,
        spec.version,
        spec.title_en,
        spec.unit,
        request,
        inputs.reporting_currency,
        frame=frame,
        notes=outcome.notes,
        concepts=outcome.concepts,
        tables=outcome.tables,
    )
