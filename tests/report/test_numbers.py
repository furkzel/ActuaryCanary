"""CV06 presentation rounding: half away from zero on the shortest decimal representation."""

import numpy as np

from actuarycanary.report import numbers


def test_cv06_examples() -> None:
    assert str(numbers.round_half_away(2.675, 2)) == "2.68"  # binary 2.67499... still 2.68
    assert str(numbers.round_half_away(-0.5, 0)) == "-1"
    assert str(numbers.round_half_away(0.5, 0)) == "1"


def test_formats() -> None:
    assert numbers.amount(1234567.5) == "1,234,568"
    assert numbers.amount(-0.4) == "0"
    assert numbers.amount(np.float64(-81337.6)) == "-81,338"
    assert numbers.factor(1.4455) == "1.446"
    assert numbers.ratio(0.6845) == "68.5%"
    assert numbers.count(7) == "7"
    assert numbers.amount(None) == numbers.EMPTY
    assert numbers.amount(float("nan")) == numbers.EMPTY
