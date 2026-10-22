"""CL02 Case reserve: hand-computed fixtures of the specification."""

from tests.measures.helpers import measure, table
from tests.measures.shared import MONTH_ENDS, four_months


def test_cl02_case_reserve_at_each_month_end_including_the_carried_forward_month() -> None:
    result = measure(four_months(), "CL02", "valuation_date")
    assert [table(result)[(d,)] for d in MONTH_ENDS] == [800.0, 700.0, 610.0, 470.0]
