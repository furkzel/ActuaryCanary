"""MT08 robust z-score flags: the hand fixture, the deviation fallbacks, groups and the
recall of injected payment outliers on the synthetic baseline."""

import math
from datetime import date

import polars as pl
import pytest

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.methods.robust_z import RobustZ, robust_z_flags
from tests.methods.medium import load_medium, medium

DAY = date(2024, 1, 31)


def _valuations(rows: list[tuple[str, date, float, float, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "claim_id": [r[0] for r in rows],
            "valuation_date": [r[1] for r in rows],
            "paid_to_date": [r[2] for r in rows],
            "case_reserve": [r[3] for r in rows],
            "currency": [r[4] for r in rows],
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        },
        schema_overrides={"valuation_date": pl.Date},
    )


def _payments(logs: list[float], currency: str = "TRY") -> pl.DataFrame:
    """One claim per value, whose single row pays exp(value)."""
    return _valuations([(f"C{k:03d}", DAY, math.exp(y), 0.0, currency) for k, y in enumerate(logs)])


def _run(valuations: pl.DataFrame, **options) -> RobustZ:
    return robust_z_flags(valuations, None, {"TRY": 1.0}, variables=("paid_flow",), **options)


def test_fixture_one_to_thirty_and_sixty_give_one_flag() -> None:
    # median 16; |y - 16| has median 8; z(60) = 0.6745 x 44 / 8
    result = _run(_payments([*range(1, 31), 60]))
    assert result.flags.height == 1
    flag = result.flags.row(0, named=True)
    assert flag["claim_id"] == "C030"
    assert flag["z"] == pytest.approx(0.6745 * 44 / 8, rel=1e-12)
    assert flag["threshold"] == 3.5
    assert flag[SOURCE_ROW] == 32
    assert flag["reason"].startswith("payment of ")
    assert "robust z 3.71, threshold 3.5" in flag["reason"]
    scores = result.scores.sort("claim_id")
    assert scores["z"][0] == pytest.approx(0.6745 * -15 / 8, rel=1e-12)
    assert result.flag_rates.row(0, named=True) | {"rate": None} == {
        "segment": "UNKNOWN",
        "line": "UNKNOWN",
        "variable": "paid_flow",
        "values": 31,
        "flagged": 1,
        "status": "scored",
        "rate": None,
    }


def test_zero_mad_falls_back_to_the_mean_absolute_deviation() -> None:
    # 20 values of 5 and 11 of 6: median 5, MAD 0, mean |d| = 11/31
    result = _run(_payments([5.0] * 20 + [6.0] * 11))
    scored = result.scores.filter(pl.col("y") > 5.5)
    assert scored["z"][0] == pytest.approx(1 / (1.253314 * 11 / 31), rel=1e-12)
    assert result.flags.height == 0


def test_no_spread_flags_nothing() -> None:
    result = _run(_payments([5.0] * 31))
    assert result.flags.height == 0
    assert set(result.scores["z"].to_list()) == {0.0}


def test_small_groups_are_not_scored() -> None:
    result = _run(_payments(list(range(1, 30))))
    assert result.scores.height == 0
    assert result.flag_rates["status"].to_list() == ["too few values"]


def test_high_flag_rate_warns_of_mixed_populations() -> None:
    result = _run(_payments([5.0] * 28 + [1.0, 9.0, 9.5]), min_group_size=30)
    assert result.flags.height == 3
    assert len(result.warnings) == 1
    assert "may mix populations" in result.warnings[0]


def test_flows_follow_consecutive_rows_and_reserve_changes_are_scored() -> None:
    rows = [
        ("A", date(2024, 1, 31), 100.0, 50.0, "USD"),
        ("A", date(2024, 2, 29), 100.0, 0.0, "USD"),  # no payment; reserve to zero
        ("A", date(2024, 3, 31), 400.0, 0.0, "USD"),  # payment of 300; no reserve either side
        ("B", date(2024, 1, 31), 10.0, 0.0, "EUR"),  # no rate: not scored, counted
    ]
    result = robust_z_flags(_valuations(rows), None, {"USD": 30.0}, min_group_size=1)
    paid = result.scores.filter(pl.col("variable") == "paid_flow").sort("valuation_date")
    assert paid["amount"].to_list() == [3000.0, 9000.0]
    reserve = result.scores.filter(pl.col("variable") == "reserve_change")
    assert reserve["y"].to_list() == [pytest.approx(math.log(1 / 1501))]
    assert result.not_converted == 1


def test_groups_come_from_claims() -> None:
    valuations = _payments([*range(1, 31), 60])
    claims = pl.DataFrame(
        {
            "claim_id": valuations["claim_id"],
            "segment": ["NON_LIFE"] * 31,
            "line": ["MOTOR_OD"] * 31,
        }
    )
    result = robust_z_flags(valuations, claims, {"TRY": 1.0}, variables=("paid_flow",))
    assert result.flags.select("segment", "line").row(0) == ("NON_LIFE", "MOTOR_OD")


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown variables"):
        robust_z_flags(_payments([1.0]), None, {}, variables=("paid",))


# Ground truth (record 0043): recall of the injected extreme payments, at least 0.75 in MT08.
# Measured 2026-10-22: 0 of 8 (their z is 1.2 to 2.5); the owner chose to keep MT08 as specified.
@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.skipif(not medium("baseline").is_dir(), reason="run `just synth baseline medium`")
@pytest.mark.xfail(strict=True, reason="recall 0 of 8 against at least 0.75 (record 0043)")
def test_ground_truth_recall_of_injected_payment_outliers() -> None:
    data = load_medium("baseline")
    result = robust_z_flags(data.valuations, data.claims, data.rates.rates)
    injected = data.faults.filter(pl.col("fault_type") == "extreme_payment_outliers").select(
        "claim_id", pl.col("date").alias("valuation_date")
    )
    paid = result.scores.filter(pl.col("variable") == "paid_flow")
    found = injected.join(paid, on=["claim_id", "valuation_date"], how="inner")
    assert found.height == injected.height  # every injected payment is scored
    recall = found["flagged"].sum() / injected.height
    others = paid.filter(pl.col("flagged")).height - found["flagged"].sum()
    print(f"recall {recall:.2f}; other flags per 1000 payments {1000 * others / paid.height:.2f}")
    assert recall >= 0.75
