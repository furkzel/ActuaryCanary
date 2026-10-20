from pathlib import Path

import pytest

from actuarycanary.synthetic.build import Simulation, simulate
from actuarycanary.synthetic.scenario import Scenario, load_with

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"


@pytest.fixture(scope="module")
def baseline() -> Simulation:
    """The baseline scenario at tiny size, simulated in memory (nothing written)."""
    return simulate("baseline", "tiny")


def simulate_with(overrides: dict, size: str = "tiny") -> Simulation:
    """The baseline with `overrides` merged on top (for example a heavier tail)."""
    scenario: Scenario = load_with("baseline", overrides)
    return simulate(scenario, size)
