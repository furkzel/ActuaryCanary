"""Earned premium per segment, line and origin period for the premium-based methods (record 0055).

It is the measure PR02 on the basis of the run, computed through the engine so that the
reserving module and the profitability measures read the same figures.
"""

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.measures.engine import run_measure
from actuarycanary.measures.model import CurrencyView, MeasureInputs, MeasureRequest, MeasureResult
from actuarycanary.modules.runner import request_for
from actuarycanary.spec.catalogue import SpecCatalogue
from actuarycanary.structures.periods import Period

PREMIUM_MEASURE = "PR02"
BREAKDOWNS = ("segment", "line", "calendar_period")


def earned_premium_by_origin(
    catalogue: SpecCatalogue,
    inputs: MeasureInputs,
    period: Period,
    reinsurance: ReinsuranceBasis,
    value: ValueBasis,
    view: CurrencyView = CurrencyView.REPORTING,
) -> tuple[pl.DataFrame | None, str, tuple[MeasureRequest, MeasureResult] | None]:
    """(premium table, reason, the PR02 request and result so the runner can reuse them).

    The table has segment, line, origin_period and earned_premium; it is None, with a reason,
    when premiums or policies are not loaded or the premium cannot be converted."""
    spec = catalogue.measures[PREMIUM_MEASURE]
    request, _ = request_for(spec, BREAKDOWNS, period, reinsurance, value, view)
    result = run_measure(catalogue, inputs, PREMIUM_MEASURE, request)
    if result.frame is None:
        return None, f"earned premium (PR02) is not available: {result.reason}", None
    frame = (
        result.frame.select(
            "segment",
            "line",
            pl.col("calendar_period").alias("origin_period"),
            pl.col("value").alias("earned_premium"),
        )
        .group_by("segment", "line", "origin_period", maintain_order=True)
        .agg(pl.col("earned_premium").sum())  # one row per currency in the ORIGINAL view
    )
    return frame, "", (request, result)
