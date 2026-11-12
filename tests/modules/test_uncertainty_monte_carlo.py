# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false
"""Calibration of the M12 reserve range on triangles drawn from the model (Monte Carlo, behind
ACTUARYCANARY_MONTE_CARLO=1).

Spec IDs proved: M12, RS05. Cells are drawn from the gamma process of the over-dispersed Poisson
model fitted to GenIns, the true reserve is the sum of the drawn cells below the diagonal, and the
range is read from the output of the module (not from MT11 directly): the true reserve must fall
below the 95th percentile of the bootstrap range in 90 to 99 per cent of the triangles, and below
the VaR at 99.5 per cent in at least 97 per cent. The Mack lognormal coverage is printed as
information (decision 0062). The paid and incurred triangles are the same numbers, so the
selected unpaid is the chain-ladder reserve and the range is not rescaled.
"""

import os
from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.convert.discount import DiscountSettings, resolve_discount
from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.modules.reserving import ChainLadderSettings, MethodInputs, run_reserving
from actuarycanary.modules.uncertainty import BOOTSTRAP_SOURCE, MACK_SOURCE, run_uncertainty
from actuarycanary.structures.triangles import Triangle, TriangleSet, TriangleSettings
from tests.methods.test_mt11_odp_bootstrap import _genins_model
from tests.modules.test_tier_b_wiring import _source

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("ACTUARYCANARY_MONTE_CARLO") != "1",
        reason="Monte Carlo test; set ACTUARYCANARY_MONTE_CARLO=1",
    ),
]

RUNS = 150
SIMULATIONS = 600
SEED = 20261107
GROUP = ("S", "L")
# own-model calibration is judged on the plain averages: the rule of record 0776 is off
NO_RULE = ChainLadderSettings(min_origins_per_factor=1)


def _triangle_set(observed: np.ndarray) -> TriangleSet:
    n = observed.shape[0]
    calendar = np.where(~np.isnan(observed), np.add.outer(np.arange(n), np.arange(n)), -1)
    counts = np.where(~np.isnan(observed), 5, -1)
    points = tuple(date(2000 + i, 12, 31) for i in range(n))
    origins, ages = tuple(str(2000 + i) for i in range(n)), tuple(12 * (j + 1) for j in range(n))
    triangles = tuple(
        Triangle(m, GROUP, origins, ages, observed, counts, calendar, points)
        for m in ("paid", "incurred")
    )
    return TriangleSet(
        TriangleSettings(), "TRY", points[-1], "accident", 0, 55, triangles, pl.DataFrame(), ()
    )


def test_the_range_of_m12_covers_the_true_reserve_of_triangles_drawn_from_the_model() -> None:
    means, phi = _genins_model()
    n = len(means)
    upper = np.add.outer(np.arange(n), np.arange(n)) <= n - 1
    rng = np.random.default_rng(SEED)
    no_curve = resolve_discount(
        DiscountSettings(), AssumptionsRegister(), None, date(2009, 12, 31), "TRY"
    )
    register = AssumptionsRegister(
        entries=(
            Assumption(
                method="MT11",
                name="n_simulations",
                scope="S/L/paid",
                value=SIMULATIONS,
                who="test",
                why="calibration",
            ),
        )  # fmt: skip
    )
    below_p95, below_var, below_mack = [], [], []
    for _ in range(RUNS):
        cells = rng.gamma(means / phi, phi)
        observed = np.where(upper, np.cumsum(np.where(upper, cells, 0.0), axis=1), np.nan)
        reserving = run_reserving(
            _triangle_set(observed), NO_RULE,
            MethodInputs(register=register, tier_b=_source()),
        )  # fmt: skip
        found = run_uncertainty(reserving, no_curve, register)
        assert not isinstance(found, str)
        true = float(cells[~upper].sum())
        boot = found.risk.filter(
            (pl.col("source") == BOOTSTRAP_SOURCE) & (pl.col("origin_period") == "Total")
        ).row(0, named=True)
        assert not found.lines[0].shifted  # the premise: the range is not rescaled
        below_p95.append(true <= boot["p95"])
        below_var.append(true <= boot["value_at_risk"])
        mack = found.risk.filter(
            (pl.col("source") == MACK_SOURCE) & (pl.col("origin_period") == "Total")
        )
        if mack.height and mack["p95"][0] is not None:
            below_mack.append(true <= mack["p95"][0])
    coverage = float(np.mean(below_p95))
    print(
        f"M12 bootstrap coverage of p95 over {RUNS} model triangles: {coverage:.3f}; of the "
        f"VaR at 99.5%: {np.mean(below_var):.3f}; Mack lognormal p95 (information): "
        f"{np.mean(below_mack):.3f} on {len(below_mack)} triangles"
    )
    assert 0.90 <= coverage <= 0.99, coverage
    assert float(np.mean(below_var)) >= 0.97
