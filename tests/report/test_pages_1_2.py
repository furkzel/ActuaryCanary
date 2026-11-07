"""The pages of report 1.2 on the tiny baseline (records 0340 to 0344): the tier B blocks of the
reserving pages, the uncertainty page, the large-loss and settlement-speed parts, the
sensitivity tables and the value basis, each read from the tables the run writes."""

import re

import pytest

from actuarycanary.pipeline import RunResult

pytestmark = pytest.mark.integration


def _page(run: RunResult, module: str) -> dict:
    return next(p for p in run.report_data["pages"] if p["module"] == module)


def test_the_reserving_page_shows_tier_a_and_tier_b_side_by_side(default_run: RunResult) -> None:
    lines = default_run.report_data["reserving"]["lines"]
    for line in lines:
        table = line["methods"]["ultimates"]
        assert len(table["headers"]) == len(table["tiers"])
        assert all(len(r["cells"]) == len(table["headers"]) for r in table["rows"])
        tier_b = line["tier_b"]
        assert set(tier_b) >= {"tails", "munich", "bootstrap", "back_test", "not_run"}
    tiers = {t for line in lines for t in line["methods"]["ultimates"]["tiers"]}
    assert tiers == {"A", "B"}  # MT13, MT15 or MT16 ran on some line of the tiny baseline
    # four origin years: no Munich and no bootstrap, each says why
    assert all(line["tier_b"]["munich"] is None for line in lines)
    assert all(line["tier_b"]["bootstrap"]["reason"] for line in lines)


def test_the_uncertainty_page_is_a_module_page_with_its_statements(default_run: RunResult) -> None:
    page = _page(default_run, "M12")
    body = page["body"]
    assert page["anchor"] == "uncertainty"
    assert body["bases"] == ["NOMINAL"] and not body["discounted"]
    assert "no curve is named" in body["discount_reason"]
    statements = body["statements"]
    assert statements["independent"] and statements["correlation"] == "0.000"
    assert not statements["all_lines_total"]


def test_the_large_loss_and_settlement_parts_read_their_files(default_run: RunResult) -> None:
    large = _page(default_run, "M06")["body"]["large"]
    assert {x["line"] for x in large["lines"]} == {
        f"{g.group[0]} · {g.group[1]}" for g in default_run.reserving.groups
    }
    assert any(x["fits"]["rows"] for x in large["lines"])  # MT17 fits MOTOR_OD
    assert all(x["tail"] is None for x in large["lines"])  # MT18 fits nothing on tiny
    survival = _page(default_run, "M03")["body"]["survival"]
    assert survival is not None and survival["lines"]
    assert all(len(x["percentiles"]) == 3 for x in survival["lines"])
    assert "no frozen reference" in survival["footnotes"]["information"]


def test_the_value_basis_without_a_curve_is_nominal_with_no_switch(default_run: RunResult) -> None:
    bases = default_run.report_data["bases"]
    assert [x["id"] for x in bases["items"]] == ["NOMINAL"]
    assert bases["shown"] == "NOMINAL" and not bases["switch"]
    page = default_run.report.read_text(encoding="utf-8")
    assert 'data-basis-shown="NOMINAL"' in page
    assert not re.search(r'<[a-z]+ [^>]*data-basis="DISCOUNTED"', page)  # no hidden block


def test_the_sensitivity_tables_are_on_the_reserving_summary(default_run: RunResult) -> None:
    found = default_run.report_data["reserving"]["sensitivity"]
    assert found is not None
    assert {b["basis"] for b in found["blocks"]} == {"NOMINAL"}
    assert any(x.startswith("no discounted figures") for x in found["reasons"])
    assert "sensitivity.csv" in found["footnote"]
