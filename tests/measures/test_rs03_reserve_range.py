"""RS03 reserve range: the lognormal of the Mack reserve and its standard error.

Spec IDs proved: RS03. R = 100 and se = 20 give sigma^2 = ln 1.04 and the hand-computed median,
VaR at 99.5 per cent and TVaR at 99 per cent. The benchmark part is in MT06
(tests/methods/test_mt06_mack.py); the range across lines and the bootstrap range beside it
are proved with RS05 and M12.
"""

import numpy as np
import pytest
from scipy.stats import norm

from actuarycanary.measures.risk import lognormal_risk
from actuarycanary.methods.mack import PERCENTILES, TVAR_LEVEL, VAR_LEVEL


def test_reserve_100_and_standard_error_20_by_hand() -> None:
    found = lognormal_risk(100.0, 20.0, PERCENTILES, VAR_LEVEL, TVAR_LEVEL)
    assert found is not None
    sigma2 = np.log(1.04)
    assert found.sigma**2 == pytest.approx(sigma2, rel=1e-14)
    assert found.mu == pytest.approx(np.log(100.0) - sigma2 / 2, rel=1e-14)
    median = 100.0 / np.sqrt(1.04)  # exp(mu)
    assert found.percentiles[0.5] == pytest.approx(median, rel=1e-13)
    z995, z99 = 2.5758293035489004, 2.3263478740408408
    assert found.value_at_risk == pytest.approx(median * np.exp(np.sqrt(sigma2) * z995), rel=1e-12)
    # TVaR = e^(mu + sigma^2/2) Phi(sigma - z) / (1 - p) with e^(mu + sigma^2/2) = the reserve
    assert found.tail_value_at_risk == pytest.approx(
        100.0 * norm.cdf(np.sqrt(sigma2) - z99) / 0.01, rel=1e-12
    )
    assert found.tail_value_at_risk > found.percentiles[0.99]


def test_no_range_for_a_reserve_that_is_not_positive_or_a_zero_standard_error() -> None:
    assert lognormal_risk(0.0, 5.0, PERCENTILES, VAR_LEVEL, TVAR_LEVEL) is None
    assert lognormal_risk(-10.0, 5.0, PERCENTILES, VAR_LEVEL, TVAR_LEVEL) is None
    assert lognormal_risk(100.0, 0.0, PERCENTILES, VAR_LEVEL, TVAR_LEVEL) is None
