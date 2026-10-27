"""MT19 on the synthetic baseline (medium) against the settlement times the generator simulated.

Spec IDs proved: MT19 (ground truth), CL08. The Kaplan-Meier median settlement time of each line
is compared with the median of the simulated times from report to the first closing of the same
claims (every claim reported by the cut-off), including the ones that close after the cut-off,
which the data do not show but the generator knows. Pass criterion of the spec: within 10 per cent
per line. Run with `-s` to see the table.
"""

import numpy as np
import polars as pl
import pytest

from actuarycanary.measures.model import MeasureInputs, with_refs
from actuarycanary.methods.survival import survival_analysis
from actuarycanary.modules.survival_run import claim_durations
from actuarycanary.synthetic.build import simulate
from actuarycanary.synthetic.days import to_day
from tests.methods.medium import load_medium, medium

pytestmark = [pytest.mark.slow, pytest.mark.integration]

TOLERANCE = 0.10


@pytest.fixture(scope="module")
def comparison():
    if not medium("baseline").is_dir():
        pytest.skip("run `just synth baseline medium` first")
    data = load_medium("baseline")
    cut_off = data.valuations["valuation_date"].max()
    inputs = MeasureInputs(
        with_refs({"claim_valuations": data.valuations, "claims": data.claims}),
        cut_off,  # type: ignore[arg-type]
        "TRY",
        data.rates,
        data.market,
        "CPI_TR",
    )
    durations, _ = claim_durations(inputs)
    result = survival_analysis(durations)
    world = simulate("baseline", "medium").world
    reported = world.c_rep <= to_day(cut_off)  # type: ignore[arg-type]
    settle = (world.c_e0 - world.c_rep).astype(float)
    rows = []
    for line in sorted(set(world.c_line)):
        mine = reported & (world.c_line == line)
        found = result.percentiles.filter(
            (pl.col("grouping") == "line")
            & (pl.col("group") == line)
            & (pl.col("percentile") == 0.5)
        )["time"][0]
        rows.append((line, found, float(np.median(settle[mine])), int(mine.sum())))
    return result, rows


def test_the_median_settlement_time_of_each_line_is_within_ten_per_cent_of_the_simulated_one(
    comparison,
) -> None:
    _, rows = comparison
    print("\nline, Kaplan-Meier median, simulated median, ratio, claims")
    for line, estimate, truth, claims in rows:
        print(f"{line:16s} {estimate:8.1f} {truth:8.1f} {estimate / truth:6.3f} {claims:6d}")
    assert len(rows) == 4
    for line, estimate, truth, _ in rows:
        assert abs(estimate / truth - 1.0) <= TOLERANCE, (line, estimate, truth)


def test_the_cox_model_of_the_non_life_segment_orders_the_lines_as_the_generator_does(
    comparison,
) -> None:
    """Information: the lines settle at very different speeds in the generator (own damage
    quickest, third-party liability slowest), so the hazard ratios must be ordered likewise."""
    result, _ = comparison
    model = result.models.filter(pl.col("segment") == "NON_LIFE").row(0, named=True)
    assert model["status"] == "fitted", model
    ratio = dict(
        zip(
            result.coefficients.filter(pl.col("segment") == "NON_LIFE")["level"].to_list(),
            result.coefficients.filter(pl.col("segment") == "NON_LIFE")["hazard_ratio"].to_list(),
            strict=True,
        )
    )
    reference = result.coefficients["reference"][0]
    ratio[reference] = 1.0
    print(
        "\nhazard ratios of closing against", reference, ratio, "concordance", model["concordance"]
    )
    assert ratio["MOTOR_TPL"] < ratio["PROPERTY"] < ratio["MOTOR_OD"]
