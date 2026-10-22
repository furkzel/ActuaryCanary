"""Diagnostics of MT02 (factor stability, residuals, averages, warnings), the thin-evidence
note of every method and negative IBNR (MT05 and the paid chain ladder)."""

import numpy as np
import pytest

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.diagnostics import (
    Diagnostic,
    chain_ladder_diagnostics,
    chain_ladder_warnings,
    negative_ibnr,
    skipped,
    thin_evidence,
)
from actuarycanary.structures.triangles import TriangleSettings, build_triangles
from tests.benchmarks.load import load_benchmark
from tests.methods.helpers import HAND, HAND_AGES, HAND_ORIGINS, array, fitted
from tests.methods.medium import ROOT, load_folder


def _codes(warnings) -> list[str]:
    return [w.code for w in warnings]


def test_hand_fixture_warnings_thin_evidence_late_development_and_few_ratios() -> None:
    cumulative = array(HAND["paid"])
    warnings = chain_ladder_warnings(fitted(cumulative), cumulative, HAND_ORIGINS, HAND_AGES)
    assert _codes(warnings) == [
        "THIN_EVIDENCE",
        "LATE_DEVELOPMENT",
        "FEW_LINK_RATIOS",
        "FEW_LINK_RATIOS",
    ]
    thin, late, two, one = warnings
    assert thin.message.startswith("only 4 origin periods: thin evidence")
    assert late.target == "36-48" and late.value == pytest.approx(1.1)
    assert "still 1.1 and the tail factor is 1.0" in late.message
    assert (two.target, two.value, one.target, one.value) == ("24-36", 2.0, "36-48", 1.0)


def test_no_late_development_warning_with_a_tail_or_a_small_last_factor() -> None:
    cumulative = array(HAND["paid"])
    with_tail = chain_ladder_warnings(
        fitted(cumulative, tail_factor=1.1), cumulative, HAND_ORIGINS, HAND_AGES
    )
    assert "LATE_DEVELOPMENT" not in _codes(with_tail)
    incurred = array(HAND["incurred"])  # last factor 1.04
    assert "LATE_DEVELOPMENT" not in _codes(
        chain_ladder_warnings(fitted(incurred), incurred, HAND_ORIGINS, HAND_AGES)
    )


def test_zero_denominator_names_the_cell_and_the_factor_without_it() -> None:
    cumulative = array(HAND["paid"])
    cumulative[2, 0] = 0.0  # origin 2023: nothing at 12 months, 190 at 24
    chain = fitted(cumulative)
    [zero] = [w for w in chain_ladder_warnings(chain, cumulative, HAND_ORIGINS, HAND_AGES)
              if w.code == "ZERO_DENOMINATOR"]  # fmt: skip
    assert chain.factors[0] == pytest.approx(570 / 200)
    assert zero.target == "2023:12-24"
    assert zero.value == pytest.approx(380 / 200)
    assert "kept by default (MT02)" in zero.message and "exclude cell 2023:12-24" in zero.message


def test_long_triangle_has_no_thin_evidence_warning() -> None:
    cumulative = array(load_benchmark("raa")["triangle"])
    origins = [str(o) for o in load_benchmark("raa")["expected"]["origins"]]
    ages = load_benchmark("raa")["expected"]["ages"]
    warnings = chain_ladder_warnings(fitted(cumulative), cumulative, origins, ages)
    assert "THIN_EVIDENCE" not in _codes(warnings)
    assert thin_evidence("MT08", 3, "years of valuations") is not None


def test_stability_residuals_and_averages_of_the_hand_fixture() -> None:
    cumulative = array(HAND["paid"])
    found = chain_ladder_diagnostics(fitted(cumulative), cumulative, HAND_ORIGINS, HAND_AGES)
    stability = found.stability
    ratios = np.array([170 / 90, 210 / 110, 190 / 100])
    assert stability.columns == ("12-24", "24-36", "36-48")
    assert stability.used.tolist() == [3, 2, 1]
    assert stability.mean[0] == pytest.approx(ratios.mean())
    assert stability.coefficient_of_variation[0] == pytest.approx(
        ratios.std(ddof=1) / ratios.mean()
    )
    assert np.isnan(stability.standard_deviation[2])
    assert set(found.averages) == {"volume_weighted", "simple", "volume_weighted_latest_3"}
    assert found.averages["simple"][0] == pytest.approx(ratios.mean())
    residuals = found.residuals
    assert residuals.values.shape == (4, 3)
    assert set(residuals.by_diagonal) <= {1, 2, 3}
    assert np.isfinite(residuals.by_column[:2]).all()


def test_negative_ibnr_on_a_paid_ultimate() -> None:
    [found] = negative_ibnr(
        "MT02", np.array([100.0, 80.0]), np.array([90.0, 95.0]), ["2024", "2025"]
    )
    assert (found.code, found.target, found.value) == ("NEGATIVE_IBNR", "2025", -15.0)
    assert "paid ultimate of origin 2025" in found.message


def test_a_skipped_method_becomes_a_diagnostic() -> None:
    found = skipped(Skipped("MT06", "too few link ratios to estimate variance"), "MT06")
    assert found is not None and found.code == "NOT_RUN"
    assert skipped(object(), "MT06") is None


@pytest.mark.slow
@pytest.mark.integration
def test_the_cases_seen_on_the_baseline_example() -> None:
    """examples/baseline (tiny, four accident years): the warnings the owner pointed out."""
    data = load_folder(ROOT / "examples" / "baseline")
    triangles = build_triangles(
        data.valuations, data.claims, TriangleSettings(), {"TRY": 1.0}, "TRY"
    )
    found: dict[tuple[str, str, str], Diagnostic] = {}
    for line in ("MOTOR_OD", "MOTOR_TPL", "PROPERTY"):
        paid = triangles.get("paid", ("NON_LIFE", line))
        incurred = triangles.get("incurred", ("NON_LIFE", line))
        chain = fitted(paid.cumulative, calendar=paid.calendar)
        warnings = chain_ladder_warnings(chain, paid.cumulative, paid.origins, paid.ages)
        warnings += negative_ibnr("MT02", chain.ultimate, incurred.latest, paid.origins)
        found |= {(line, w.code, w.target): w for w in warnings}
    assert found[("MOTOR_TPL", "LATE_DEVELOPMENT", "36-48")].value == pytest.approx(1.38, abs=5e-3)
    assert "factor 12-24 is 4.459" in found[("PROPERTY", "ZERO_DENOMINATOR", "2024:12-24")].message
    assert {("MOTOR_OD", "NEGATIVE_IBNR", "2025"), ("MOTOR_TPL", "NEGATIVE_IBNR", "2025")} <= set(
        found
    )
    assert ("MOTOR_OD", "THIN_EVIDENCE", "") in found
