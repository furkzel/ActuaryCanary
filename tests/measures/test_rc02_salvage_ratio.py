"""RC02 Salvage ratio: hand-computed fixtures of the specification."""

import pytest

from tests.measures.helpers import make_inputs, measure, one
from tests.quality.builders import cv


def test_rc02_salvage_ratio() -> None:
    rows = [cv(1, paid_to_date=1000.0, case_reserve=0.0, salvage_to_date=30.0)]
    assert one(
        measure(make_inputs({"claim_valuations": rows}), "RC02", "origin_period")
    ) == pytest.approx(0.03)
