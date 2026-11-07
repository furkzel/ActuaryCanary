"""Claim sizes of a synthetic medium folder, built as CV08 builds them (the severity methods take
exactly this frame; the wiring of the pipeline does the same in the integration item).

Sizes come from `size_classes` (gross incurred at the cut-off, reporting currency, restated to
value-date prices when the index is loaded); segment, line, event code and origin year from the
claims header; the status is the latest one of the claim.
"""

from pathlib import Path

import polars as pl

from actuarycanary.measures.claim_base import header, size_classes, status_rows
from actuarycanary.measures.model import MeasureInputs, MeasureRequest, with_refs
from tests.methods.medium import load_medium, medium


def available(scenario: str) -> bool:
    return medium(scenario).is_dir()


def claim_sizes(scenario: str) -> tuple[pl.DataFrame, dict[tuple[str, str], float], Path]:
    """(sizes frame, CV08 threshold by (segment, line), truth folder) of a scenario at medium."""
    data = load_medium(scenario)
    cut_off = data.valuations["valuation_date"].max()
    inputs = MeasureInputs(
        with_refs({"claim_valuations": data.valuations, "claims": data.claims}),
        cut_off,  # type: ignore[arg-type]
        "TRY",
        data.rates,
        data.market,
        "CPI_TR",
    )
    request = MeasureRequest()
    classes, _ = size_classes(inputs, request)
    head = header(inputs, request).select(
        "claim_id", "segment", "line", "event_code", pl.col("origin_period").cast(pl.Int64)
    )
    status = (
        status_rows(inputs)
        .sort("claim_id", "valuation_date")
        .group_by("claim_id", maintain_order=True)
        .agg(pl.col("status").last())
    )
    frame = (
        classes.join(head, on="claim_id")
        .join(status, on="claim_id")
        .rename({"origin_period": "origin_year"})
        .select(
            "claim_id", "size", "status", "segment", "line", "event_code", "origin_year",
            "claim_size_class", "threshold",
        )
    )  # fmt: skip
    thresholds = {
        (s, line): t
        for s, line, t in frame.group_by("segment", "line")
        .agg(pl.col("threshold").first())
        .iter_rows()
        if t is not None
    }
    return frame, thresholds, data.truth
