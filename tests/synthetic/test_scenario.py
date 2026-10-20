"""Scenario files: validation, `extends` and sizes."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from actuarycanary.synthetic.scenario import (
    list_scenarios,
    load_scenario,
    load_with,
    merge,
    sized,
)

NAMES = ["baseline", "messy_headers", "high_inflation", "large_loss", "reserve_bias_change"]


def test_the_five_scenarios_exist():
    assert set(NAMES) <= set(list_scenarios())


@pytest.mark.parametrize("name", NAMES)
def test_every_scenario_file_loads_and_has_the_three_sizes(name):
    scenario = load_scenario(name)
    assert scenario.name == name
    assert {"tiny", "medium", "large"} <= set(scenario.sizes)


def test_extends_merges_dictionaries_and_replaces_lists():
    base, messy = load_scenario("baseline"), load_scenario("messy_headers")
    assert not base.messiness.personal_data and messy.messiness.personal_data
    assert messy.lines == base.lines  # nothing else changed
    changed = load_scenario("reserve_bias_change")
    assert len(base.reserving_practice_changes) == 1
    assert len(changed.reserving_practice_changes) == 2  # the list is replaced, not appended to


def test_one_nested_value_can_be_overridden_without_repeating_the_rest():
    scenario = load_with(
        "baseline", {"lines": {"MOTOR_TPL": {"frequency": {"per_exposure_year": 0.5}}}}
    )
    tpl = scenario.lines["MOTOR_TPL"]
    assert tpl.frequency.per_exposure_year == 0.5
    assert tpl.frequency.trend_per_year == 0.0
    assert tpl.severity == load_scenario("baseline").lines["MOTOR_TPL"].severity


def test_merge_does_not_change_its_inputs():
    base, over = {"a": {"b": 1}, "c": [1]}, {"a": {"d": 2}, "c": [2]}
    assert merge(base, over) == {"a": {"b": 1, "d": 2}, "c": [2]}
    assert base == {"a": {"b": 1}, "c": [1]}


def test_a_misspelt_parameter_is_rejected():
    with pytest.raises(ValidationError):
        load_with("baseline", {"lines": {"MOTOR_OD": {"frequency": {"per_exposure_yeer": 1}}}})


def test_a_treaty_on_an_unknown_line_is_rejected():
    treaty = {
        "treaty_id": "X",
        "type": "QUOTA_SHARE",
        "lines": ["NOPE"],
        "cession": 0.1,
        "inception": "2016-01-01",
    }
    with pytest.raises(ValidationError, match="unknown line NOPE"):
        load_with("baseline", {"reinsurance": [treaty]})


def test_a_premium_needs_exactly_one_basis():
    premium = {"rate_on_sum_insured": 0.01, "per_policy": 5}
    with pytest.raises(ValidationError, match="exactly one"):
        load_with("baseline", {"lines": {"MOTOR_OD": {"premium": premium}}})


def test_scenario_files_that_extend_each_other_in_a_loop_are_rejected(tmp_path: Path):
    (tmp_path / "a.yaml").write_text(yaml.safe_dump({"extends": "b"}))
    (tmp_path / "b.yaml").write_text(yaml.safe_dump({"extends": "a"}))
    with pytest.raises(ValueError, match="loop"):
        load_scenario("a", tmp_path)


def test_unknown_size_is_reported_with_the_known_ones():
    with pytest.raises(KeyError, match="tiny"):
        sized(load_scenario("baseline"), "huge")
