"""MT01 ground truth: triangles of the synthetic baseline (medium) equal the generator's truth.

The truth file `ibnr_by_valuation.csv` holds paid and incurred per line, accident year and
quarter end from the true transactions. The spreadsheets carry injected faults on top, so
the expected cell is the truth plus each fault's known effect: an extreme payment adds its
amount from its row on. A row with an empty currency has no effect: it takes the one currency
of its claim (DV-CLV-03, claim_valuations 1.2.0). A paid_to_date lowered by an unknown amount
cannot be restated, so the cells where such a row is the as-of row are not compared and are
counted.
"""

from pathlib import Path

import polars as pl
import pytest

from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.io.excel import read_workbook
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import TriangleSettings, build_triangles

ROOT = Path(__file__).parents[2]
MEDIUM = ROOT / "data" / "synthetic" / "baseline" / "medium"
CACHE = ROOT / ".cache"
RTOL = 1e-9  # MT01 ground truth tolerance (relative)
CELL = ["segment", "line", "accident_year", "valuation_date"]

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def _fault_effects(
    faults: pl.DataFrame, valuations: pl.DataFrame, claims: pl.DataFrame, points: list
) -> tuple[pl.DataFrame, set[tuple]]:
    effects: list[tuple] = []
    uncomparable: set[tuple] = set()
    for fault in faults.iter_rows(named=True):
        claim_id, day = fault["key"].split("|")
        header = claims.filter(pl.col("claim_id") == claim_id).row(0, named=True)
        rows = valuations.filter(pl.col("claim_id") == claim_id).sort("valuation_date")
        if set(rows["currency"].to_list()) - {"UNKNOWN"} != {"TRY"}:
            continue  # the claim is not in the TRY triangle
        faulted = rows.filter(pl.col("valuation_date") == pl.lit(day).str.to_date()).row(
            0, named=True
        )
        dates = rows["valuation_date"].to_list()
        for point in points:
            known = [d for d in dates if d <= point]
            if not known:
                continue
            as_of = max(known)
            cell = (header["segment"], header["line"], header["occurrence_date"].year, point)
            match fault["fault_type"]:
                case "extreme_payment_outliers" if as_of >= faulted["valuation_date"]:
                    spike = float(fault["detail"].split()[2])
                    effects += [(*cell, "paid", spike), (*cell, "incurred", spike)]
                case "paid_to_date_decreasing_without_recovery" if (
                    as_of == faulted["valuation_date"]
                ):
                    uncomparable.add(cell)
    frame = (
        pl.DataFrame(effects, schema=[*CELL, "measure", "effect"], orient="row")
        .group_by([*CELL, "measure"])
        .agg(pl.col("effect").sum())
    )
    return frame, uncomparable


@pytest.mark.skipif(not MEDIUM.is_dir(), reason="run `just synth baseline medium` first")
def test_baseline_medium_quarterly_triangles_equal_the_truth() -> None:
    specs = load_specs()
    valuations = canonicalise(
        read_workbook(MEDIUM / "claim_valuations.xlsx", CACHE).table(),
        specs.data["claim_valuations"],
    ).frame
    claims = canonicalise(
        read_workbook(MEDIUM / "claims.xlsx", CACHE).table(), specs.data["claims"]
    ).frame
    result = build_triangles(
        valuations,
        claims,
        TriangleSettings(development_period=Period.QUARTER),
        {"TRY": 1.0},
        "TRY",
    )
    cells = [
        (
            *t.group,
            int(origin),
            t.valuation_points[t.calendar[i, j]],
            t.measure,
            float(t.cumulative[i, j]),
        )
        for t in result.triangles
        for i, origin in enumerate(t.origins)
        for j in range(len(t.ages))
        if t.observed[i, j]
    ]
    built = pl.DataFrame(cells, schema=[*CELL, "measure", "value"], orient="row")
    truth = (
        pl.read_csv(MEDIUM / "truth" / "ibnr_by_valuation.csv", try_parse_dates=True)
        .filter(pl.col("currency") == "TRY")
        .unpivot(index=CELL, on=["paid", "incurred"], variable_name="measure", value_name="truth")
    )
    faults = pl.read_csv(MEDIUM / "truth" / "injected_faults.csv").filter(
        pl.col("file") == "claim_valuations.xlsx"
    )
    points = sorted(set(built["valuation_date"].to_list()))
    effects, uncomparable = _fault_effects(faults, valuations, claims, points)

    compared = (
        truth.join(built, on=[*CELL, "measure"], how="full", coalesce=True)
        .join(effects, on=[*CELL, "measure"], how="left")
        .with_columns(pl.col("effect").fill_null(0.0))
    )
    assert compared.filter(pl.col("truth").is_null() | pl.col("value").is_null()).height == 0
    keep = [tuple(r) not in uncomparable for r in compared.select(CELL).iter_rows()]
    compared = compared.filter(pl.Series(keep))
    expected = pl.col("truth") + pl.col("effect")
    wrong = compared.filter(
        (pl.col("value") - expected).abs() > RTOL * expected.abs().clip(lower_bound=1.0)
    )
    assert wrong.height == 0, wrong.head(10)
    assert compared.height > 1500  # cells compared
    assert len(uncomparable) < 0.05 * compared.height
