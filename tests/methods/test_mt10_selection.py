"""MT10 ultimate selection: the maturity rule, overrides and the fallbacks."""

import numpy as np

from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson, bornhuetter_ferguson
from actuarycanary.methods.chain_ladder import Skipped
from actuarycanary.methods.selection import Choice, Selection, select_ultimates
from tests.methods.helpers import fitted

TRIANGLE = np.array(
    [
        [10.0, 17.0, 30.0, 33.0],
        [20.0, 33.0, 61.0, np.nan],
        [30.0, 51.0, np.nan, np.nan],
        [40.0, np.nan, np.nan, np.nan],
    ]
)
# selected factors so that the latest cells have maturities 1, 0.9, 0.5 and 0.3 exactly
# as floats: CDF(2) = 1/0.9, CDF(1) = 1.8/0.9 = 2, CDF(0) = 2/0.6 = 1/0.3
SELECTED = {0: 0.5 / 0.3, 1: 1.8, 2: 1 / 0.9}


def _chain():
    return fitted(TRIANGLE, selected=SELECTED)


def _select(**options) -> Selection:
    chain = _chain()
    bf = bornhuetter_ferguson(chain, [200.0] * 4, 0.5)
    result = select_ultimates(chain, bf, **options)
    assert isinstance(result, Selection)
    return result


def test_maturities_09_05_03_select_cl_cl_bf() -> None:
    result = _select()
    np.testing.assert_allclose(result.maturity[1:], [0.9, 0.5, 0.3], rtol=1e-12)
    assert result.method[1:] == (
        Choice.CHAIN_LADDER,
        Choice.CHAIN_LADDER,
        Choice.BORNHUETTER_FERGUSON,
    )
    chain = _chain()
    bf = bornhuetter_ferguson(chain, [200.0] * 4, 0.5)
    assert isinstance(bf, BornhuetterFerguson)
    assert result.ultimate[3] == bf.ultimate[3]
    assert result.ultimate[2] == chain.ultimate[2]


def test_override_switches_the_second_to_bf() -> None:
    result = _select(overrides={2: Choice.BORNHUETTER_FERGUSON})
    assert result.method[2] is Choice.BORNHUETTER_FERGUSON
    assert result.why[2] == "override in the assumptions register"


def test_bf_not_available_falls_back_to_chain_ladder_with_the_reason() -> None:
    chain = _chain()
    result = select_ultimates(chain, Skipped("MT03", "no prior loss ratio available"))
    assert isinstance(result, Selection)
    assert result.method[3] is Choice.CHAIN_LADDER
    assert result.why[3].endswith("not available: no prior loss ratio available")
    np.testing.assert_allclose(result.ultimate, chain.ultimate)
    paid = np.array([1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(result.unpaid(paid), chain.ultimate - paid)


def test_no_chain_ladder_no_selection() -> None:
    reason = "chain ladder needs at least 3 origin periods"
    assert select_ultimates(Skipped("MT02", reason), None) == Skipped("MT10", reason)
