"""The observed coverage of a range in the back-test (A1a, R12, record 0753).

A range is only as good as the share of later outcomes it caught. The back-test (MT22 with AE02,
`back_test.csv`, rows `range_calibration`) gives, per line, method and horizon, the number of
origins tested and how many of the later outcomes fell inside the 90 per cent range given at
the earlier valuation. This module pools those rows and writes the sentence that stands beside
every range. It recalibrates nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from actuarycanary.modules import reserving_tier_b_output as tier_b_output
from actuarycanary.report import numbers
from actuarycanary.report.frames import table
from actuarycanary.report.language import t

MACK_METHOD = "MT06"
BOOTSTRAP_METHOD = "MT11"


@dataclass(frozen=True)
class Coverage:
    inside: int
    n: int  # origin and horizon cases tested

    @property
    def share(self) -> float:
        return self.inside / self.n


def observed(
    tables: Mapping[str, pl.DataFrame],
    method: str,
    segment: str | None = None,
    line: str | None = None,
) -> Coverage | None:
    """Coverage of the ranges of `method` for one line, or pooled over all lines when no line
    is given; None when no back-test of that method exists."""
    frame = table(tables, tier_b_output.BACK_TEST_NAME)
    if not frame.height or "kind" not in frame.columns:
        return None
    found = frame.filter((pl.col("kind") == "range_calibration") & (pl.col("method") == method))
    if segment is not None and line is not None:
        found = found.filter((pl.col("segment") == segment) & (pl.col("line") == line))
    if not found.height:
        return None
    n = int(found["origins"].fill_null(0).sum())
    if n <= 0:
        return None
    return Coverage(int(found["inside"].fill_null(0).sum()), n)


def sentence(found: Coverage | None) -> str:
    """The text that stands beside a 90 per cent range."""
    if found is None:
        return t("90% range; no back-test")
    return t(
        "90% range; observed coverage in back-test {share} (n = {n})",
        share=numbers.ratio(found.share),
        n=numbers.count(found.n),
    )
