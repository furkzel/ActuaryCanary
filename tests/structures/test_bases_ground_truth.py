"""Inflation-adjusted and net triangles of the synthetic baseline (medium) against a plain
loop that restates claim by claim with no polars: the vectorised path and the loop must agree.

Claims with any row that the data rules touch (unknown currency, an empty amount, a paid
amount that decreases) are left out of both sides, so the comparison covers the bases
themselves: flows from consecutive rows, average, period-end and index lookups in three
currencies, carry-forward and the cut-off aligned development points.
"""

import calendar
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.market import MarketData
from actuarycanary.io.excel import RawTable, read_workbook
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSettings, build_triangles

ROOT = Path(__file__).parents[2]
MEDIUM = ROOT / "data" / "synthetic" / "baseline" / "medium"
CACHE = ROOT / ".cache"

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def _month(day: Any) -> int:
    return day.year * 12 + day.month - 1


def _market_tables(market: pl.DataFrame) -> tuple[dict, dict, dict]:
    """(average, end, index) lookups: {(series, month): value} straight from the rows."""
    average: dict = {}
    end: dict = {}
    index: dict = {}
    for series, kind, day, value in market.select("series_id", "kind", "date", "value").iter_rows():
        key = (series, _month(day))
        if kind == "FX_PERIOD_AVERAGE":
            average[key] = value
        elif kind == "FX_PERIOD_END":
            end[key] = value
        elif kind == "PRICE_INDEX":
            index[key] = value
    return average, end, index


def _oracle(
    valuations: pl.DataFrame, claims: pl.DataFrame, market: pl.DataFrame, net: bool
) -> dict[tuple, float]:
    """Cumulative restated paid and incurred by (segment, line, origin year, point year)."""
    average, end, index = _market_tables(market)
    cut_off = valuations["valuation_date"].max()
    assert isinstance(cut_off, date)
    value_month = _month(cut_off)
    base = index[("CPI_TR", value_month)]
    header = {r["claim_id"]: r for r in claims.iter_rows(named=True)}
    by_claim: dict[str, list[dict]] = defaultdict(list)
    for row in valuations.sort("claim_id", "valuation_date", "_source_row").iter_rows(named=True):
        by_claim[row["claim_id"]].append(row)

    def rate(table: dict, currency: str, month: int) -> float:
        return 1.0 if currency == "TRY" else table[(f"{currency}/TRY", month)]

    cells: dict[tuple, float] = defaultdict(float)
    for claim_id, rows in by_claim.items():
        origin_year = header[claim_id]["occurrence_date"].year
        states: list[tuple[date, float, float]] = []  # (date, restated paid, restated incurred)
        paid = ceded = 0.0
        paid_before = ceded_before = 0.0
        for row in rows:
            month = _month(row["valuation_date"])
            factor = base / index[("CPI_TR", month)]
            currency = row["currency"]
            flow_rate = rate(average, currency, month)
            paid += (row["paid_to_date"] - paid_before) * flow_rate * factor
            paid_before = row["paid_to_date"]
            reserve = row["case_reserve"] * rate(end, currency, month) * factor
            ceded_flow = row["ceded_paid_to_date"] or 0.0
            ceded += (ceded_flow - ceded_before) * flow_rate * factor
            ceded_before = ceded_flow
            ceded_reserve = (row["ceded_reserve"] or 0.0) * rate(end, currency, month) * factor
            if net:
                states.append(
                    (row["valuation_date"], paid - ceded, paid - ceded + reserve - ceded_reserve)
                )
            else:
                states.append((row["valuation_date"], paid, paid + reserve))
        group = (header[claim_id]["segment"], header[claim_id]["line"], origin_year)
        for year in range(origin_year, cut_off.year + 1):
            point = date(year, cut_off.month, calendar.monthrange(year, cut_off.month)[1])
            known = [s for s in states if s[0] <= point]
            if known:
                cells[(*group, year, "paid")] += known[-1][1]
                cells[(*group, year, "incurred")] += known[-1][2]
    return cells


@pytest.mark.skipif(not MEDIUM.is_dir(), reason="run `just synth baseline medium` first")
@pytest.mark.parametrize("net", [False, True])
def test_adjusted_triangles_equal_a_plain_loop(net: bool) -> None:
    specs = load_specs()

    def feed(name: str, concept: str) -> pl.DataFrame:
        workbook = read_workbook(MEDIUM / name, CACHE)
        frames = [t.frame for t in workbook.tables]
        table = RawTable(name, pl.concat(frames, how="diagonal_relaxed"))
        return canonicalise(table, specs.data[concept]).frame

    valuations = feed("claim_valuations.xlsx", "claim_valuations")
    claims = feed("claims.xlsx", "claims")
    market = feed("market.xlsx", "market")
    touched = valuations.group_by("claim_id").agg(
        (
            pl.col("currency").is_in(["TRY", "USD", "EUR"]).not_().any()
            | pl.col("paid_to_date").is_null().any()
            | pl.col("case_reserve").is_null().any()
            | (pl.col("paid_to_date").diff() < 0).any()
        ).alias("touched")
    )
    clean = touched.filter(~pl.col("touched"))["claim_id"]
    valuations = valuations.filter(pl.col("claim_id").is_in(clean.implode())).sort(
        "claim_id", "valuation_date", "_source_row"
    )
    claims = claims.filter(
        pl.col("claim_id").is_in(clean.implode()) & pl.col("occurrence_date").is_not_null()
    )
    valuations = valuations.filter(pl.col("claim_id").is_in(claims["claim_id"].implode()))

    settings = TriangleSettings(
        origin_period=Period.YEAR,
        development_period=Period.YEAR,
        value_basis=ValueBasis.INFLATION_ADJUSTED,
        reinsurance_basis=ReinsuranceBasis.NET if net else ReinsuranceBasis.GROSS,
    )
    result = build_triangles(
        valuations,
        claims,
        settings,
        {"TRY": 1.0},
        "TRY",
        market=MarketData.from_frame(market),
        price_index="CPI_TR",
    )
    expected = _oracle(valuations, claims, market, net)
    checked = 0
    for triangle in result.triangles:
        for i, origin in enumerate(triangle.origins):
            for j in range(len(triangle.ages)):
                if not triangle.observed[i, j]:
                    continue
                point = triangle.valuation_points[triangle.calendar[i, j]]
                key = (*triangle.group, int(origin), point.year, triangle.measure)
                assert triangle.cumulative[i, j] == pytest.approx(
                    expected.get(key, 0.0), rel=1e-9, abs=1e-6
                ), key
                checked += 1
    assert checked > 100
    assert {"USD", "EUR"} <= set(valuations["currency"].unique())  # foreign claims are compared
    assert result.not_converted.height == 0
