"""MT09 isolation forest flags: hand-computed features, determinism and row order, group
sizes, and the ranking of claims with injected faults on the synthetic baseline."""

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.methods.isolation_forest import (
    FEATURES,
    claim_features,
    isolation_forest_flags,
)
from tests.methods.medium import AMOUNT_FAULTS, load_medium, medium

CUT_OFF = date(2024, 12, 31)


def _valuations(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "claim_id": [r[0] for r in rows],
            "valuation_date": [r[1] for r in rows],
            "paid_to_date": [r[2] for r in rows],
            "case_reserve": [r[3] for r in rows],
            "status": [r[4] for r in rows],
            "currency": [r[5] for r in rows],
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        },
        schema_overrides={"valuation_date": pl.Date},
    )


def test_features_of_two_claims_by_hand() -> None:
    rows = [
        ("A", date(2024, 1, 31), 0.0, 100.0, "OPEN", "TRY"),
        ("A", date(2024, 6, 30), 60.0, 100.0, "OPEN", "TRY"),
        ("A", date(2024, 9, 30), 50.0, 20.0, "OPEN", "TRY"),  # paid lowered by 10
        ("B", date(2024, 3, 31), 10.0, 0.0, "CLOSED", "USD"),
    ]
    claims = pl.DataFrame(
        {
            "claim_id": ["A", "B"],
            "segment": ["NON_LIFE", "NON_LIFE"],
            "occurrence_date": [date(2024, 1, 1), date(2024, 3, 1)],
            "report_date": [date(2024, 1, 11), date(2024, 3, 1)],
        }
    )
    features = claim_features(_valuations(rows), claims, {"TRY": 1.0, "USD": 30.0}, CUT_OFF)
    a, b = features.sort("claim_id").iter_rows(named=True)
    assert a["log_incurred"] == pytest.approx(math.log(71))
    assert a["log_paid"] == pytest.approx(math.log(51))
    assert a["paid_share"] == pytest.approx(50 / 70)
    assert a["months_since_first_valuation"] == 11
    assert a["reserve_change_share"] == pytest.approx(1 / 2)
    assert a["log_largest_payment"] == pytest.approx(math.log(61))
    assert a["largest_log_reserve_change"] == pytest.approx(abs(math.log(21 / 101)))
    assert a["negative_payments"] == 1
    assert a["open"] == 1
    assert a["reporting_delay_days"] == 10
    assert b["log_paid"] == pytest.approx(math.log(301))
    assert b["paid_share"] == 1.0
    assert (b["reserve_change_share"], b["largest_log_reserve_change"], b["open"]) == (0, 0, 0)
    assert list(features.columns) == ["claim_id", "segment", *FEATURES]


def _synthetic(n: int, seed: int = 7) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    data = {name: rng.normal(size=n) for name in FEATURES}
    data["log_incurred"][0] = 25.0  # one claim far from the rest
    return pl.DataFrame({"claim_id": [f"C{k:04d}" for k in range(n)], "segment": ["S"] * n, **data})


def test_same_seed_same_scores_and_row_order_does_not_matter() -> None:
    features = _synthetic(150)
    one = isolation_forest_flags(features, n_estimators=50)
    two = isolation_forest_flags(features.reverse(), n_estimators=50)
    assert one.scores.equals(two.scores)
    assert one.flags["claim_id"].to_list()[0] == "C0000"
    assert one.flags.height == math.ceil(0.01 * 150)
    assert one.flags["reason"][0].startswith("isolation score ")
    assert "log_incurred 25.0" in one.flags["reason"][0]


def test_small_groups_are_not_scored() -> None:
    result = isolation_forest_flags(_synthetic(99), n_estimators=10)
    assert result.scores.height == 0
    assert result.groups.row(0, named=True) == {
        "segment": "S",
        "claims": 99,
        "flagged": 0,
        "status": "too few claims",
    }


# Ground truth (record 0043): claims with injected faults should rank higher; AUC at least 0.7.
# Measured 2026-10-22 on the claims whose amounts the faults changed: AUC 0.63 (all faulted
# claims 0.55); the owner chose to keep MT09 as specified.
def _auc(scores: np.ndarray, positive: np.ndarray) -> float:
    """Mann–Whitney form of the area under the ROC curve, ties counted half."""
    ranks = pl.Series(scores).rank("average").to_numpy()
    n_pos, n_neg = positive.sum(), (~positive).sum()
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.skipif(not medium("baseline").is_dir(), reason="run `just synth baseline medium`")
@pytest.mark.xfail(strict=True, reason="AUC 0.63 against at least 0.7 (record 0043)")
def test_ground_truth_claims_with_amount_faults_rank_higher() -> None:
    data = load_medium("baseline")
    cut_off = data.valuations["valuation_date"].max()
    assert isinstance(cut_off, date)
    features = claim_features(data.valuations, data.claims, data.rates.rates, cut_off)
    result = isolation_forest_flags(features)
    faults = data.faults.filter(pl.col("file") == "claim_valuations.xlsx")
    scores = result.scores["score"].to_numpy()
    amount = faults.filter(pl.col("fault_type").is_in(AMOUNT_FAULTS))["claim_id"]
    every = result.scores["claim_id"].is_in(faults["claim_id"].implode()).to_numpy()
    positive = result.scores["claim_id"].is_in(amount.implode()).to_numpy()
    print(f"AUC amount faults {_auc(scores, positive):.3f}, all faults {_auc(scores, every):.3f}")
    assert positive.sum() == amount.n_unique()
    assert _auc(scores, positive) >= 0.7
