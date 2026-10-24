from pathlib import Path

import pytest

from actuarycanary.synthetic.build import Simulation, simulate
from actuarycanary.synthetic.scenario import Scenario, load_with

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"

NO_FAULTS = {
    "injected_faults": {
        "duplicate_valuation_rows": 0,
        "report_before_occurrence": 0,
        "paid_to_date_decreasing_without_recovery": 0,
        "extreme_payment_outliers": 0,
        "missing_currency": 0,
        "unknown_status_labels": 0,
    }
}


@pytest.fixture(scope="module")
def baseline() -> Simulation:
    """The baseline scenario at tiny size, simulated in memory (nothing written)."""
    return simulate("baseline", "tiny")


def simulate_with(overrides: dict, size: str = "tiny") -> Simulation:
    """The baseline with `overrides` merged on top (for example a heavier tail)."""
    scenario: Scenario = load_with("baseline", overrides)
    return simulate(scenario, size)


def simulate_named(name: str, overrides: dict | None = None, size: str = "tiny") -> Simulation:
    """A scenario file by name with `overrides` merged on top."""
    return simulate(load_with(name, overrides or {}), size)


@pytest.fixture(scope="module")
def clean_baseline() -> Simulation:
    """The baseline without injected faults, so that the feeds can be compared exactly."""
    return simulate_named("baseline", NO_FAULTS)


@pytest.fixture(scope="module")
def heavy() -> Simulation:
    """The reinsurance_heavy scenario without injected faults."""
    return simulate_named("reinsurance_heavy", NO_FAULTS)


@pytest.fixture(scope="module")
def life() -> Simulation:
    """The life_book scenario without injected faults."""
    return simulate_named("life_book", NO_FAULTS)


@pytest.fixture(scope="module")
def life_big() -> Simulation:
    """The life_book scenario with ten times the contracts of tiny, so that every kind of event
    (reinstatements included) occurs."""
    return simulate_named("life_book", {**NO_FAULTS, "sizes": {"tiny": {"portfolio_scale": 0.02}}})
