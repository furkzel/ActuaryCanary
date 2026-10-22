"""The only door to method outputs that measures use (decision 0050).

Measures never import methods. RT01 and RT02 read the selected ultimates, AE01 the factors
selected at an earlier valuation, and RS01 to RS03 are method outputs. Until the methods exist
the port answers "not available" with the reason, and the measures say so.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import polars as pl

NO_METHODS = "needs the methods that select and project ultimates (MT03 to MT10), not built yet"


@dataclass(frozen=True)
class NotAvailable:
    reason: str


@dataclass(frozen=True)
class Selection:
    """What the selection method (MT10) says at one valuation date.

    `ultimates` is the selected ultimate by (segment, line, origin label) and `cdfs` the
    cumulative factors to ultimate by (measure, segment, line), then by development age in
    months, for the measures "paid" and "incurred". `expected` is the ultimate AE01 measures
    development against where it is not the selected one: the prior ultimate of an origin
    whose selection was Bornhuetter–Ferguson (record 0056).
    """

    valuation_date: date
    ultimates: Mapping[tuple[str, str, str], float] = field(default_factory=dict)
    cdfs: Mapping[tuple[str, str, str], Mapping[int, float]] = field(default_factory=dict)
    expected: Mapping[tuple[str, str, str], float] = field(default_factory=dict)


class MethodsPort(Protocol):
    """`basis` is the label of the basis the measure is asked on; a port whose results are on
    another basis answers "not available" instead of mixing them. Empty: any."""

    def selection(self, valuation_date: date, basis: str = "") -> Selection | NotAvailable:
        """The selection as of `valuation_date`."""
        ...

    def measure(self, measure_id: str, basis: str = "") -> pl.DataFrame | NotAvailable:
        """The table of a measure that is a method output (RS01, RS02, RS03)."""
        ...

    def built(self) -> frozenset[str]:
        """IDs of the methods that exist behind this port."""
        ...


class NoMethods:
    """The port before the methods exist."""

    def selection(self, valuation_date: date, basis: str = "") -> Selection | NotAvailable:
        return NotAvailable(NO_METHODS)

    def measure(self, measure_id: str, basis: str = "") -> pl.DataFrame | NotAvailable:
        return NotAvailable(NO_METHODS)

    def built(self) -> frozenset[str]:
        return frozenset()
