"""Typed shapes of measure results, requests and inputs (blueprint 8, decision 0050).

A measure result is a polars frame with one row per value: the requested breakdown columns,
`value` (null where the spec says "not computed", with a `note`), the numerator and
denominator of ratios, and for lineage one list of source references per concept
(`refs_<concept>`, positions in the canonical feed handed to the engine). The result carries
the spec ID and version, so every value says which rule produced it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import MarketData
from actuarycanary.convert.rates import DevelopmentRates
from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.measures.port import MethodsPort, NoMethods
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSet

REF = "_ref"  # position of a row in its canonical feed
REFS_PREFIX = "refs_"
VALUE = "value"
NOTE = "note"


class CurrencyView(StrEnum):
    ORIGINAL = "ORIGINAL"
    REPORTING = "REPORTING"  # FUNCTIONAL equals REPORTING in version 1.0 (CV01)


@dataclass(frozen=True)
class Basis:
    """The reinsurance, currency and value bases of CV01 to CV03 a measure is asked on."""

    reinsurance: ReinsuranceBasis = ReinsuranceBasis.GROSS
    currency: CurrencyView = CurrencyView.REPORTING
    value: ValueBasis = ValueBasis.NOMINAL

    def label(self) -> str:
        return f"{self.reinsurance.value}, {self.currency.value}, {self.value.value}"


@dataclass(frozen=True)
class MeasureRequest:
    """Grain and breakdowns asked for. `period` is the length of origin and calendar periods;
    `earlier` is the first valuation of the measures that compare two (CL11, AE01), the
    cut-off minus one year by default."""

    breakdowns: tuple[str, ...] = ()
    period: Period = Period.YEAR
    basis: Basis = field(default_factory=Basis)
    view: str = ""  # a variant the spec names, for example "paid" or "incurred" in RT01
    earlier: date | None = None
    params: tuple[tuple[str, Any], ...] = ()  # spec parameters, e.g. ("exclude_nil", False)

    def param(self, name: str, default: Any) -> Any:
        return dict(self.params).get(name, default)


@dataclass(frozen=True)
class MeasureResult:
    """The values of one measure for one request, or the reason there are none."""

    measure: str
    version: str
    title: str
    unit: str
    request: MeasureRequest
    reporting_currency: str
    frame: pl.DataFrame | None = None
    reason: str = ""  # why the measure is not available (frame is None)
    notes: tuple[str, ...] = ()  # things the reader should know: exclusions, flags, labels
    concepts: tuple[str, ...] = ()  # concepts the `refs_<concept>` columns refer to
    tables: Mapping[str, pl.DataFrame] = field(default_factory=dict)  # secondary tables

    @property
    def available(self) -> bool:
        return self.frame is not None

    @property
    def rows(self) -> int:
        return 0 if self.frame is None else self.frame.height

    def breakdown_columns(self) -> list[str]:
        if self.frame is None:
            return []
        return [c for c in self.request.breakdowns if c in self.frame.columns]


@dataclass(frozen=True)
class Missing:
    """Returned by a measure function that cannot produce values."""

    reason: str


@dataclass(frozen=True)
class Computed:
    """Returned by a measure function: the frame, notes and the concepts its refs point to."""

    frame: pl.DataFrame
    notes: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    tables: Mapping[str, pl.DataFrame] = field(default_factory=dict)


@dataclass
class MeasureInputs:
    """What measures read: canonical feeds (each with a `_ref` column), the cut-off, the
    conversion data and the outputs of other components (triangles, methods)."""

    feeds: Mapping[str, pl.DataFrame]
    cut_off: date
    reporting_currency: str
    rates: DevelopmentRates
    market: MarketData | None = None
    price_index: str | None = None
    value_date: date | None = None  # CV02 prices; None: the cut-off
    fiscal_year_start_month: int = 1
    origin_axis: str = "accident"
    triangles: TriangleSet | None = None
    methods: MethodsPort = field(default_factory=NoMethods)
    large_loss_percentile: float = 0.99  # CV08 defaults
    min_claims_for_percentile: int = 100
    large_loss_thresholds: Mapping[tuple[str, str], float] = field(default_factory=dict)
    # the MT18 threshold beside CV08's, as a sentence for the notes of CL12 (information only)
    extreme_value_note: str = ""
    cache: dict[Any, Any] = field(default_factory=dict)

    def has(self, concept: str, name: str | None = None) -> bool:
        frame = self.feeds.get(concept)
        return frame is not None and (name is None or name in frame.columns)

    def source_index(self, concept: str) -> pl.DataFrame:
        """file, sheet and row of every `_ref` of a concept."""
        frame = self.feeds[concept]
        columns = [c for c in SOURCE_COLUMNS if c in frame.columns]
        return frame.select(REF, *columns)


def with_refs(feeds: Mapping[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    """The feeds with the `_ref` column that lineage points to."""
    return {
        concept: frame.with_row_index(REF) if REF not in frame.columns else frame
        for concept, frame in feeds.items()
    }
