"""RI05 Loss ratio volatility, gross and net: five origin years with gross and net loss ratios
give the hand-computed deviations and ratio.

Spec IDs proved: RI05.
"""

import statistics
from datetime import date

import polars as pl
import pytest

from actuarycanary.measures.port import NotAvailable
from actuarycanary.measures.reinsurance_programme import volatility_frame
from tests.measures.helpers import make_inputs
from tests.quality.builders import cv, policy, premium

YEARS = (2020, 2021, 2022, 2023, 2024)
ULTIMATE = (600.0, 700.0, 500.0, 900.0, 800.0)
NET_SHARE = (0.7, 0.6, 0.8, 0.5, 0.6)


class Ultimates:
    """A port that answers RS02 with selected ultimates."""

    def __init__(self, years=YEARS) -> None:
        self.years = years

    def selection(self, valuation_date, basis=""):
        return NotAvailable("not part of the stub")

    def measure(self, measure_id, basis=""):
        return pl.DataFrame(
            {
                "segment": ["NON_LIFE"] * len(self.years),
                "line": ["L"] * len(self.years),
                "origin_period": [str(y) for y in self.years],
                "method": ["selected"] * len(self.years),
                "ultimate": list(ULTIMATE[: len(self.years)]),
            }
        )

    def built(self):
        return frozenset({"MT10"})


def _inputs(years=YEARS):
    rows = {
        "claim_valuations": [cv(12, claim_id="Z")],
        "policies": [
            policy(
                policy_id=f"P{y}",
                start_date=date(y, 1, 1),
                end_date=date(y + 1, 1, 1),
                segment="NON_LIFE",
                line="L",
            )
            for y in years
        ],
        "premiums": [
            premium(
                transaction_id=f"W{y}", policy_id=f"P{y}", booking_date=date(y, 1, 1), amount=1000.0
            )
            for y in years
        ],
    }
    return make_inputs(rows, cut_off=date(2024, 12, 31), methods=Ultimates(years))


def _net(years=YEARS) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "segment": ["NON_LIFE"] * len(years),
            "line": ["L"] * len(years),
            "year": list(years),
            "net_share": list(NET_SHARE[: len(years)]),
        },
        schema={"segment": pl.String, "line": pl.String, "year": pl.Int64, "net_share": pl.Float64},
    )


def test_ri05_five_origins_by_hand() -> None:
    frame, _ = volatility_frame(_inputs(), _net())
    row = frame.row(0, named=True)
    gross = [u / 1000 for u in ULTIMATE]
    net = [u * s / 1000 for u, s in zip(ULTIMATE, NET_SHARE, strict=True)]
    assert row["denominator"] == pytest.approx(statistics.stdev(gross), rel=1e-9)
    assert row["numerator"] == pytest.approx(statistics.stdev(net), rel=1e-9)
    assert row["value"] == pytest.approx(statistics.stdev(net) / statistics.stdev(gross), rel=1e-9)
    assert row["loss_view"] == "ultimate" and row["origin_years"] == "2020, 2021, 2022, 2023, 2024"


def test_ri05_needs_five_origin_years() -> None:
    frame, _ = volatility_frame(_inputs(YEARS[:4]), _net(YEARS[:4]))
    row = frame.row(0, named=True)
    assert row["value"] is None and "fewer than 5" in row["note"]
