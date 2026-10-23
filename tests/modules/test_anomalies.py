"""M06: the flags of MT08 and MT09 as one table with score, reason and source rows."""

import math
from datetime import date

import polars as pl
import pytest

from actuarycanary.convert.rates import DevelopmentRates
from actuarycanary.io.excel import SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET
from actuarycanary.modules.anomalies import ANOMALY_COLUMNS, run_anomalies, spans
from actuarycanary.pipeline import RunResult
from tests.methods.helpers import reserve_flag_shares
from tests.methods.test_mt08_robust_z import MAX_RESERVE_SHARE

DAY = date(2024, 1, 31)
RATES = DevelopmentRates({"TRY": 1.0}, DAY)


def _valuations(logs: list[float], currency: str = "TRY") -> pl.DataFrame:
    """One claim per value, whose single row pays exp(value)."""
    count = len(logs)
    return pl.DataFrame(
        {
            "claim_id": [f"C{k:03d}" for k in range(count)],
            "valuation_date": [DAY] * count,
            "paid_to_date": [math.exp(y) for y in logs],
            "case_reserve": [0.0] * count,
            "status": ["CLOSED"] * count,
            "currency": [currency] * count,
            SOURCE_FILE: ["claim_valuations.xlsx"] * count,
            SOURCE_SHEET: ["claim_valuations"] * count,
            SOURCE_ROW: list(range(2, count + 2)),
        },
        schema_overrides={"valuation_date": pl.Date},
    )


def test_rows_are_written_as_spans() -> None:
    assert spans([4, 2, 3, 9, 9, 10, 20]) == "2-4;9-10;20"
    assert spans([5]) == "5"
    assert spans([]) == ""


def test_one_outlying_payment_becomes_one_flag_with_its_row_and_reason() -> None:
    # median 16, the median absolute deviation 8: z(60) = 0.6745 x 44 / 8 = 3.71 (MT08 fixture)
    result = run_anomalies(_valuations([*range(1, 31), 60]), None, RATES, DAY)
    flags = result.flags
    assert flags.columns == list(ANOMALY_COLUMNS)
    assert flags.height == 1
    flag = flags.row(0, named=True)
    assert flag["method"] == "MT08" and flag["claim_id"] == "C030"
    assert flag["variable"] == "paid_flow"
    assert flag["score"] == pytest.approx(0.6745 * 44 / 8, rel=1e-12)
    assert flag["threshold"] == 3.5
    assert (flag["file"], flag["sheet"], flag["rows"]) == (
        "claim_valuations.xlsx",
        "claim_valuations",
        "32",
    )
    assert "robust z 3.71, threshold 3.5" in flag["reason"]
    assert result.counts().row(0) == ("MT08", "UNKNOWN", "UNKNOWN", 1)
    # the claim groups are too small for the forest, and the module says so
    assert result.reasons == ("MT09: 1 group has too few claims to score",)


def test_a_currency_without_a_rate_is_left_out_and_said() -> None:
    result = run_anomalies(_valuations([*range(1, 31), 60], currency="USD"), None, RATES, DAY)
    assert result.flags.height == 0
    assert any(r.startswith("MT08: 31 values left out") for r in result.reasons)


def test_reserve_movements_of_the_baseline_are_not_mostly_flagged(default_run: RunResult) -> None:
    shares = reserve_flag_shares(default_run.anomalies.robust)
    assert {"MOTOR_OD", "MOTOR_TPL"} <= set(shares)
    assert max(shares.values()) <= MAX_RESERVE_SHARE
