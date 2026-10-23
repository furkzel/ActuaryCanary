"""The engine refuses what the specification does not define, reports what is missing, and
records spec, version and source rows with every value (blueprint 8, decision 0050)."""

import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.measures.engine import IMPLEMENTATIONS, METHOD_OUTPUTS
from actuarycanary.measures.output import _ranges, lineage_table, values_table
from actuarycanary.measures.port import NO_METHODS, NotAvailable
from actuarycanary.structures.periods import Period
from tests.measures.helpers import CATALOGUE, make_inputs, measure, one
from tests.quality.builders import cv

ROWS = [cv(1, paid_to_date=10.0), cv(2, paid_to_date=25.0)]  # spreadsheet rows 2 and 3


def test_every_measure_of_version_1_has_a_function_or_comes_from_elsewhere() -> None:
    wanted = {m for module in CATALOGUE.modules.values() for m in module.measures}
    assert wanted <= set(IMPLEMENTATIONS) | set(METHOD_OUTPUTS) | {"DQ01"}
    version_1 = {
        *(f"PR0{n}" for n in range(1, 7)),
        *(f"CL{n:02d}" for n in range(1, 13)),
        "RC01",
        "RC02",
        "RI01",
        "RI02",
        "EX01",
        "EX02",
        "EX03",
        "RT01",
        "RT02",
        "AE01",
    }
    assert version_1 <= set(IMPLEMENTATIONS)


def test_a_breakdown_the_spec_does_not_define_is_refused_with_the_ones_it_does() -> None:
    result = measure(make_inputs({"claim_valuations": ROWS}), "CL02", "calendar_period")
    assert not result.available
    assert "no breakdown by calendar_period" in result.reason and "origin_period" in result.reason


def test_a_basis_the_spec_does_not_define_is_refused() -> None:
    inputs = make_inputs({"claim_valuations": ROWS, "premiums": []})
    result = measure(inputs, "PR04", reinsurance=ReinsuranceBasis.NET)
    assert result.reason == "PR04 is not defined on the NET basis; its bases are GROSS"


def test_a_breakdown_the_spec_allows_but_this_version_does_not_build_says_where_to_look() -> None:
    result = measure(make_inputs({"claim_valuations": ROWS}), "CL01", "development_period")
    assert "triangles" in result.reason


def test_missing_required_fields_are_named_by_concept_and_column() -> None:
    result = measure(make_inputs({"claim_valuations": ROWS}), "CL05")
    assert result.reason == "claims is not loaded; policies is not loaded"
    no_column = make_inputs({"claim_valuations": ROWS}).feeds["claim_valuations"].drop("status")
    inputs = make_inputs({"claim_valuations": ROWS})
    inputs.feeds = {**inputs.feeds, "claim_valuations": no_column}  # type: ignore[misc]
    assert measure(inputs, "CL04").reason == "claim_valuations has no status column"


def test_method_outputs_come_only_through_the_port() -> None:
    inputs = make_inputs({"claim_valuations": ROWS})
    for measure_id in ("RS01", "RS02", "RS03"):
        assert measure(inputs, measure_id).reason == NO_METHODS
    assert isinstance(inputs.methods.measure("RS02"), NotAvailable)


def test_values_carry_the_spec_id_and_version_and_the_basis() -> None:
    result = measure(make_inputs({"claim_valuations": ROWS}), "CL01", "valuation_date")
    table = values_table([result])
    assert set(table["measure"]) == {"CL01"}
    assert set(table["version"]) == {CATALOGUE.measures["CL01"].version}
    assert set(table["basis"]) == {"GROSS, REPORTING, NOMINAL"}
    assert table["value"].to_list() == [10.0, 25.0]
    assert table["key"].to_list()[0].startswith("valuation_date=2024-01-31")


def test_lineage_points_to_the_source_rows_by_file_sheet_and_row() -> None:
    inputs = make_inputs({"claim_valuations": ROWS})
    stock = measure(inputs, "CL01", "origin_period")
    # the value at the cut-off stands on the latest row of the claim: spreadsheet row 3
    lineage = lineage_table([stock], inputs)
    assert lineage.to_dicts() == [
        {
            "measure": "CL01",
            "version": CATALOGUE.measures["CL01"].version,
            "view": "origin_period",
            "row": 0,
            "concept": "claim_valuations",
            "file": "f.xlsx",
            "sheet": "s",
            "rows": "3",
            "count": 1,
        }
    ]
    flows = measure(inputs, "CL01", "calendar_period", period=Period.MONTH)
    # a flow stands on both rows it is the difference of
    assert lineage_table([flows], inputs)["rows"].to_list() == ["2", "3"]


def test_lineage_compresses_runs_of_rows_into_ranges() -> None:
    rows = [cv(1, claim_id=f"K{i}", paid_to_date=1.0) for i in range(5)]
    inputs = make_inputs({"claim_valuations": rows})
    lineage = lineage_table([measure(inputs, "CL01")], inputs)
    assert lineage["rows"].to_list() == ["2-6"] and lineage["count"].to_list() == [5]


def test_ranges_start_a_new_run_at_a_gap_a_repeat_and_a_new_key() -> None:
    frame = pl.DataFrame(
        {
            "row": [0, 0, 0, 0, 0, 1, 1, 1],
            "file": ["a", "a", "a", "a", "a", "a", "b", "b"],
            "sheet": ["s"] * 8,
            "source_row": [9, 2, 3, 4, 4, 7, 6, 5],
        }
    )
    ranges = _ranges(frame, ["row", "file", "sheet"])
    assert ranges["row"].to_list() == [0, 1, 1]
    assert ranges["file"].to_list() == ["a", "a", "b"]
    assert ranges["rows"].to_list() == ["2-4;4;9", "7", "5-6"]
    assert ranges["count"].to_list() == [5, 1, 2]


def test_premium_values_point_to_premium_and_policy_rows() -> None:
    from tests.quality.builders import policy, premium

    inputs = make_inputs(
        {"claim_valuations": [cv(1)], "premiums": [premium()], "policies": [policy()]}
    )
    result = measure(inputs, "PR02", "segment")
    table = lineage_table([result], inputs)
    assert set(table["concept"]) == {"premiums", "policies"}


def test_a_result_that_is_not_available_has_no_values_and_no_lineage() -> None:
    inputs = make_inputs({"claim_valuations": ROWS})
    result = measure(inputs, "RS01")
    assert values_table([result]).height == 0
    assert lineage_table([result], inputs).height == 0
    assert isinstance(values_table([result]), pl.DataFrame)


def test_edge_case_zero_value_is_a_value_and_missing_is_not() -> None:
    """Paid zero is a computed 0, not a missing value (PR01 and CL01 differ from 'not computed')."""
    result = measure(make_inputs({"claim_valuations": [cv(1, paid_to_date=0.0)]}), "CL01")
    assert one(result) == 0.0


def test_values_file_has_no_negative_zero() -> None:
    inputs = make_inputs({"claim_valuations": [cv(1, paid_to_date=-0.0, case_reserve=0.0)]})
    table = values_table([measure(inputs, "CL01")])
    assert [str(v) for v in table["value"].to_list()] == ["0.0"]
