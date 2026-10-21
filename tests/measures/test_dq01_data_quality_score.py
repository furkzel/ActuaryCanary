"""DQ01: the weighted pass rate of the validation rules."""

from actuarycanary.quality.engine import dq01
from actuarycanary.quality.model import RuleScore


def rule(severity: str, weight: int, checked: int, failed: int) -> RuleScore:
    return RuleScore("R", "claims", "validity", severity, weight, (), checked, failed)


def test_dq01_weights_blocking_three_warning_one_info_zero() -> None:
    score = dq01(
        [rule("BLOCKING", 3, 100, 10), rule("WARNING", 1, 100, 50), rule("INFO", 0, 100, 100)]
    )
    assert score.value is not None
    assert abs(score.value - 80.0) < 1e-12  # 100 (3 x 0.9 + 1 x 0.5) / 4
    assert score.rules == 3


def test_rule_that_checks_zero_rows_adds_nothing() -> None:
    score = dq01([rule("BLOCKING", 3, 0, 0), rule("WARNING", 1, 10, 1)])
    assert score.value == 90.0 and score.rules == 1


def test_only_info_rules_give_no_score() -> None:
    assert dq01([rule("INFO", 0, 10, 10)]).value is None
    assert dq01([]).value is None


def test_clean_data_scores_one_hundred() -> None:
    assert dq01([rule("BLOCKING", 3, 5, 0), rule("WARNING", 1, 5, 0)]).value == 100.0
