"""MT17 and MT18 on the synthetic scenarios (medium) against the severity truth of the generator
(`truth/severity_truth.csv`, `truth/severity_tail_truth.csv`).

Spec IDs proved: MT17, MT18 (ground truth), CV08 (the extreme-value threshold never classifies).

The specifications ask for these comparisons "as information" with no tolerance: the generator
mixes a body with a Pareto tail, adds superimposed inflation and a litigation multiplier, which no
single family reproduces. The assertions below are sanity bounds of this test, set from the run of
2026-10-25 (decision 0302), not tolerances of the specifications. Run with `-s` to see the table.
"""

import math

import polars as pl
import pytest

from actuarycanary.methods.severity import extreme_values, fit_severity
from tests.methods.severity.medium_sizes import available, claim_sizes

pytestmark = [pytest.mark.slow, pytest.mark.integration]

NON_LIFE_LINES = ("MOTOR_OD", "MOTOR_TPL", "PROPERTY")


def _need(scenario: str) -> None:
    if not available(scenario):
        pytest.skip(f"run `just synth {scenario} medium` first")


@pytest.fixture(scope="module")
def baseline():
    _need("baseline")
    frame, thresholds, truth_folder = claim_sizes("baseline")
    truth = pl.read_csv(truth_folder / "severity_truth.csv")
    fits = fit_severity(frame)
    tail = extreme_values(frame, cv08_thresholds=thresholds)
    return frame, thresholds, truth, fits, tail


@pytest.fixture(scope="module")
def large_loss():
    _need("large_loss")
    frame, thresholds, _ = claim_sizes("large_loss")
    return frame, thresholds, extreme_values(frame, cv08_thresholds=thresholds)


def _line(frame: pl.DataFrame, line: str) -> dict:
    rows = frame.filter(pl.col("line") == line)
    assert rows.height == 1, (line, rows)
    return rows.row(0, named=True)


def test_every_line_with_enough_closed_claims_is_fitted_and_gets_a_family(baseline) -> None:
    _, _, truth, fits, _ = baseline
    groups = fits.groups.filter(pl.col("status") == "fitted")
    assert set(NON_LIFE_LINES) <= set(groups["line"])
    assert groups["claims"].min() >= 50
    assert fits.selected["family"].null_count() == 0
    assert set(truth["line"]) <= set(fits.selected["line"])


def test_the_fitted_scale_of_each_line_agrees_with_the_truth_up_to_one_common_factor(
    baseline,
) -> None:
    # sizes are at value-date prices and the truth at base-date prices: the ratio of the fitted
    # 90th percentile to the true one is the price level (and superimposed inflation) and must be
    # about the same for every line
    _, _, truth, fits, _ = baseline
    ratios = {}
    for line in NON_LIFE_LINES:
        fitted = fits.quantiles.filter((pl.col("line") == line) & (pl.col("probability") == 0.90))
        ratios[line] = fitted["quantile"][0] / _line(truth, line)["quantile_0_9"]
    centre = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
    print(
        "\nMT17 fitted 90th percentile over the true one:",
        {k: round(v, 2) for k, v in ratios.items()},
    )
    assert all(0.7 < r / centre < 1.3 for r in ratios.values()), ratios


def test_the_trend_of_sizes_by_year_finds_the_superimposed_inflation(baseline) -> None:
    _, _, truth, fits, _ = baseline
    for line in ("MOTOR_OD", "MOTOR_TPL"):
        found = _line(fits.trend_summary, line)["annual_change"]
        wanted = _line(truth, line)["superimposed_inflation"]
        print(f"\nMT17 trend {line}: found {found:.4f}, generator {wanted:.4f}")
        assert found == pytest.approx(wanted, abs=0.015)
    assert any(d.code == "SEVERITY_TREND" for d in fits.diagnostics)


def test_the_tail_index_is_the_right_order_of_the_reciprocal_pareto_index(baseline) -> None:
    _, _, truth, _, tail = baseline
    rows = []
    for line in NON_LIFE_LINES:
        fitted = _line(tail.gpd_fit, line)
        wanted = _line(truth, line)["tail_xi"]
        thresholds = _line(tail.thresholds, line)
        rows.append(
            (
                line,
                wanted,
                fitted["xi"],
                fitted["xi_interval_low"],
                fitted["xi_interval_high"],
                thresholds["threshold"],
                _line(truth, line)["tail_threshold"],
            )
        )
        assert 0.5 < fitted["xi"] / wanted < 2.0, (line, fitted["xi"], wanted)
    print("\nMT18 line, true xi, fitted xi, interval, selected u, scenario tail start")
    for row in rows:
        name, true_xi, xi, low, high, u, start = row
        print(f"  {name:<10} {true_xi:.3f} {xi:.3f} [{low:.3f}, {high:.3f}] {u:.0f} {start:.0f}")


def test_the_extreme_value_threshold_is_reported_but_never_classifies(baseline) -> None:
    frame, thresholds, _, _, tail = baseline
    comparison = tail.threshold_comparison
    for row in comparison.iter_rows(named=True):
        group = (row["segment"], row["line"])
        assert row["cv08_threshold"] == thresholds[group]
        # LARGE claims are the ones at or above the CV08 threshold, whatever MT18 selected
        large = frame.filter(
            (pl.col("segment") == group[0])
            & (pl.col("line") == group[1])
            & (pl.col("claim_size_class") == "LARGE")
        ).height
        assert large <= row["claims_at_or_above_cv08"] + 1  # events and nil claims differ by a few
        assert row["extreme_value_threshold"] < row["cv08_threshold"]  # u sits well below the 99th
        assert row["claim_share_extreme_value"] > row["claim_share_cv08"]
    print(
        "\n"
        + str(
            comparison.select(
                "line",
                "extreme_value_threshold",
                "claim_share_extreme_value",
                "incurred_share_extreme_value",
                "cv08_threshold",
                "claim_share_cv08",
                "incurred_share_cv08",
            )
        )
    )


def test_a_tail_with_infinite_mean_gives_quantiles_but_no_expected_shortfall(large_loss) -> None:
    _, _, tail = large_loss
    assert tail.thresholds["status"].to_list() == ["fitted"] * tail.thresholds.height
    for row in tail.gpd_fit.iter_rows(named=True):
        shortfall = tail.tail_quantiles.filter(
            (pl.col("line") == row["line"]) & (pl.col("probability") == 0.995)
        )["expected_shortfall"][0]
        flagged = any(
            d.code == "INFINITE_MEAN_TAIL" and row["line"] in d.message for d in tail.diagnostics
        )
        assert flagged == (row["xi"] >= 1.0)
        assert math.isnan(shortfall) == (row["xi"] >= 1.0)
