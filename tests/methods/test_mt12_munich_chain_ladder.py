"""MT12 Munich chain ladder: 4 x 4 fixture recomputed by hand, benchmark, properties and
failure modes."""

import math

import numpy as np
import pytest

from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.munich import Munich, munich_chain_ladder
from tests.methods.helpers import HAND, array, fitted
from tests.methods.tier_b import series, triangle, value

MCL = "MT12-munich-chain-ladder-mcl"
NAN = np.nan
# the paid triangle of the hand fixture with an incurred triangle whose link ratios vary in every
# column (the hand fixture's incurred has the same ratio twice in column 24-36, sigma zero)
INCURRED_4X4 = np.array(
    [[200.0, 250.0, 280.0, 290.0], [220.0, 270.0, 300.0, NAN], [180.0, 240.0, NAN, NAN],
     [190.0, NAN, NAN, NAN]]
)  # fmt: skip


def _run(paid, incurred, **options) -> Munich:
    result = munich_chain_ladder(paid, incurred, **options)
    assert isinstance(result, Munich)
    return result


Hand = tuple[
    tuple[float, float], list[float], list[float], dict[tuple[int, int], tuple[float, float]]
]


def _by_hand(paid: list[list[float]], incurred: list[list[float]]) -> Hand:
    """The spec formulas cell by cell with plain floats, for a full upper triangle."""
    n = len(paid)

    def factors(t):
        return [sum(t[i][j + 1] for i in range(n - 1 - j)) / sum(t[i][j] for i in range(n - 1 - j))
                for j in range(n - 1)]  # fmt: skip

    def sigma2(t, f):
        s = []
        for j in range(n - 1):
            k = n - 1 - j
            if k >= 2:
                s.append(
                    sum(t[i][j] * (t[i][j + 1] / t[i][j] - f[j]) ** 2 for i in range(k)) / (k - 1)
                )
            else:
                s.append(min(s[-1] ** 2 / s[-2], s[-2], s[-1]))
        return s

    fp, fi = factors(paid), factors(incurred)
    sp = [math.sqrt(v) for v in sigma2(paid, fp)]
    si = [math.sqrt(v) for v in sigma2(incurred, fi)]
    q = [sum(paid[i][j] for i in range(n - j)) / sum(incurred[i][j] for i in range(n - j))
         for j in range(n)]  # fmt: skip
    rho_i, rho_p = [], []
    for j in range(n - 1):
        m = n - j
        rho_i.append(math.sqrt(sum(incurred[i][j] * (paid[i][j] / incurred[i][j] - q[j]) ** 2
                                   for i in range(m)) / (m - 1)))  # fmt: skip
        rho_p.append(math.sqrt(sum(paid[i][j] * (incurred[i][j] / paid[i][j] - 1 / q[j]) ** 2
                                   for i in range(m)) / (m - 1)))  # fmt: skip
    num_p = den_p = num_i = den_i = 0.0
    for j in range(n - 2):  # the last link is left out
        for i in range(n - 1 - j):
            rp = (paid[i][j + 1] / paid[i][j] - fp[j]) / sp[j] * math.sqrt(paid[i][j])
            qp = (incurred[i][j] / paid[i][j] - 1 / q[j]) / rho_p[j] * math.sqrt(paid[i][j])
            ri = (incurred[i][j + 1] / incurred[i][j] - fi[j]) / si[j] * math.sqrt(incurred[i][j])
            qi = (paid[i][j] / incurred[i][j] - q[j]) / rho_i[j] * math.sqrt(incurred[i][j])
            num_p, den_p = num_p + qp * rp, den_p + qp * qp
            num_i, den_i = num_i + qi * ri, den_i + qi * qi
    lp, li = num_p / den_p, num_i / den_i
    ult_p, ult_i, corrected = [], [], {}
    for i in range(n):
        p, c = paid[i][n - 1 - i], incurred[i][n - 1 - i]
        for j in range(n - 1 - i, n - 1):
            fpj = fp[j] + lp * sp[j] / rho_p[j] * (c / p - 1 / q[j])
            fij = fi[j] + li * si[j] / rho_i[j] * (p / c - q[j])
            corrected[(i, j)] = (fpj, fij)
            p, c = p * fpj, c * fij
        ult_p.append(p)
        ult_i.append(c)
    return (lp, li), ult_p, ult_i, corrected


def test_hand_fixture_lambda_corrected_factors_and_ultimates() -> None:
    paid, incurred = array(HAND["paid"]), INCURRED_4X4
    lambdas, ult_p, ult_i, corrected = _by_hand(
        np.nan_to_num(paid).tolist(), np.nan_to_num(incurred).tolist()
    )
    result = _run(paid, incurred, min_origins=4)
    assert (result.lambda_paid, result.lambda_incurred) == pytest.approx(lambdas, rel=1e-9)
    np.testing.assert_allclose(result.paid_ultimate, ult_p, rtol=1e-9)
    np.testing.assert_allclose(result.incurred_ultimate, ult_i, rtol=1e-9)
    for (i, j), (fp, fi) in corrected.items():
        got_p = result.projected_paid[i, j + 1] / result.projected_paid[i, j]
        got_i = result.projected_incurred[i, j + 1] / result.projected_incurred[i, j]
        assert (got_p, got_i) == pytest.approx((fp, fi), rel=1e-9)
    assert result.n_pairs == (5, 5)


def test_benchmark_against_the_package() -> None:
    paid, _, _ = triangle(MCL, "paid.csv")
    incurred, _, _ = triangle(MCL, "incurred.csv")
    result = _run(paid, incurred)
    assert result.lambda_paid == pytest.approx(value(MCL, "lambda", "paid"), rel=1e-6)
    assert result.lambda_incurred == pytest.approx(value(MCL, "lambda", "incurred"), rel=1e-6)
    np.testing.assert_allclose(result.paid_ultimate, series(MCL, "munich_paid_ultimate"), rtol=1e-6)
    np.testing.assert_allclose(
        result.incurred_ultimate, series(MCL, "munich_incurred_ultimate"), rtol=1e-6
    )
    np.testing.assert_allclose(
        result.projected_ratios[:, -1], series(MCL, "munich_paid_to_incurred_ratio"), rtol=1e-6
    )
    gap = result.paid_incurred_gap
    assert np.abs(gap["munich"]).sum() < np.abs(gap["chain_ladder"]).sum()
    np.testing.assert_allclose(
        result.paid_chain.ultimate, series(MCL, "chain_ladder_paid_ultimate"), rtol=1e-6
    )


def test_lambda_zero_gives_the_separate_chain_ladders() -> None:
    paid, _, _ = triangle(MCL, "paid.csv")
    incurred, _, _ = triangle(MCL, "incurred.csv")
    result = _run(paid, incurred, lambdas=(0.0, 0.0))
    np.testing.assert_allclose(result.paid_ultimate, fitted(paid).ultimate, rtol=1e-12)
    np.testing.assert_allclose(result.incurred_ultimate, fitted(incurred).ultimate, rtol=1e-12)


def test_failure_modes() -> None:
    paid, incurred = array(HAND["paid"]), array(HAND["incurred"])
    assert munich_chain_ladder(paid, incurred) == Skipped(
        "MT12", "Munich chain ladder needs at least 5 origin periods"
    )
    with pytest.raises(ValueError, match="same cells"):
        munich_chain_ladder(paid, incurred[:, :3])
    mcl_paid, _, _ = triangle(MCL, "paid.csv")
    mcl_incurred, _, _ = triangle(MCL, "incurred.csv")
    zero = mcl_incurred.copy()
    zero[1, 0] = 0.0
    result = _run(mcl_paid, zero)
    assert [d.code for d in result.diagnostics] == ["ZERO_INCURRED"]
    assert not result.pairs_incurred[1, 0] and not result.pairs_paid[1, 0]
    flat_paid = mcl_incurred * 0.5  # every ratio 0.5: rho is zero in every column
    flat = _run(flat_paid, mcl_incurred)
    assert {d.code for d in flat.diagnostics} == {"ZERO_RATIO_VARIANCE"}
    np.testing.assert_allclose(flat.paid_ultimate, fitted(flat_paid).ultimate, rtol=1e-12)
