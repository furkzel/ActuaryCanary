import importlib

import pytest

SUBPACKAGES = [
    "io",
    "recognition",
    "canonical",
    "quality",
    "convert",
    "structures",
    "measures",
    "methods",
    "modules",
    "report",
    "manifest",
    "spec",
    "cli",
    "synthetic",
]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports_and_is_documented(name: str) -> None:
    module = importlib.import_module(f"actuarycanary.{name}")
    assert module.__doc__
