"""A1a: one reconciled total (R07), the bridge from the selected unpaid to the simulated mean
(R05) and the present-value tables that hold one definition each (R06), record 0752."""

from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from actuarycanary.modules.uncertainty import ALL_LINES, DISCOUNTED, NOMINAL
from actuarycanary.pipeline import RunResult
from actuarycanary.report.uncertainty_section import (
    bridge_of,
    bridge_table,
    headline,
    present_values,
    ranges,
    selected_totals,
)

ORIGINS = ("2020", "2021", "2022")


def test_the_bridge_of_a_scaled_line_adds_up_to_the_cent() -> None:
    # origin 2022 is fully developed in the simulated triangle: selected 20.50, simulated 0
    selected = np.array([100.0, 50.0, 20.5])
    sims = np.array([[90.0, 40.0, 0.0], [110.0, 60.0, 0.0], [95.0, 45.0, 0.0], [105.0, 55.0, 0.0]])
    found = bridge_of(ORIGINS, selected, sims)
    assert found.selected == 170.5
    assert found.left_out == 20.5 and found.left_out_origins == (("2022", 20.5),)
    assert found.other == pytest.approx(0.0, abs=1e-12)
    assert found.mean == 150.0
    assert round(found.balance, 2) == round(found.mean, 2) == 150.0


def test_the_bridge_of_an_unscaled_line_keeps_the_sampling_difference_in_its_own_step() -> None:
    selected = np.array([100.0, 50.0])
    sims = np.array([[101.0, 49.0], [103.0, 51.0]])  # means 102 and 50
    found = bridge_of(ORIGINS[:2], selected, sims)
    assert found.left_out == 0.0 and found.left_out_origins == ()
    assert found.other == pytest.approx(2.0)
    assert found.selected - found.left_out + found.other == pytest.approx(152.0)


def test_an_origin_with_nothing_selected_is_not_left_out() -> None:
    found = bridge_of(ORIGINS[:2], np.array([0.0, 10.0]), np.array([[0.0, 9.0], [0.0, 11.0]]))
    assert found.left_out == 0.0 and found.left_out_origins == ()
    assert found.other == 0.0 and found.mean == 10.0
    noise = bridge_of(ORIGINS[:2], np.array([-1.86e-9, 10.0]), np.array([[0.0, 9.0], [0.0, 11.0]]))
    assert noise.left_out == 0.0 and noise.left_out_origins == ()


def _risk(rows: list[tuple[str, str, str, str, float, float | None, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "segment": a,
                "line": b,
                "origin_period": "Total",
                "source": src,
                "value_basis": basis,
                "mean": mean,
                "nominal_mean": before,
                "discount_effect": effect,
                "p95": mean * 1.2,
                "standard_deviation": mean * 0.1,
                "coefficient_of_variation": 0.1,
            }
            for a, b, src, basis, mean, before, effect in rows
        ]
    )


def test_the_discounted_headline_row_adds_up_and_the_expected_cash_flows_have_their_own_table() -> (
    None
):
    risk = _risk(
        [
            ("S", "L", "bootstrap", DISCOUNTED, 60.0, 100.0, 40.0),
            ("S", "L", "expected_cash_flows", DISCOUNTED, 62.0, 101.0, 39.0),
        ]
    )
    [row] = headline(risk, pl.DataFrame(), DISCOUNTED, {("S", "L"): 101.0})
    assert (row["nominal"], row["effect"], row["reserve"]) == ("100", "40", "60")
    assert float(row["nominal"]) - float(row["effect"]) == float(row["reserve"])
    [pv] = present_values(risk)
    assert (pv["selected"], pv["effect"], pv["present"]) == ("101", "39", "62")
    assert float(pv["selected"]) - float(pv["effect"]) == float(pv["present"])


def test_the_total_of_all_lines_is_the_sum_of_the_selected_unpaid_of_the_lines() -> None:
    class _Line:
        def __init__(self, key: tuple[str, str], total: float) -> None:
            self.key, self.selected_total = key, total

    totals = selected_totals((_Line(("A", "x"), 10.5), _Line(("A", "y"), 4.25)))  # type: ignore[arg-type]
    assert totals[(ALL_LINES, ALL_LINES)] == 14.75
    assert selected_totals(()) == {}


class _Line:
    def __init__(
        self, key: tuple[str, str], selected: list[float], sims: list[list[float]]
    ) -> None:
        self.key = key
        self.origins = ORIGINS[: len(selected)]
        self.selected_unpaid = np.array(selected)
        self.origin_sims = np.array(sims) if sims else None
        self.selected_total = float(np.sum(selected))


def test_the_bridge_table_has_the_steps_as_rows_and_the_lines_and_all_lines_as_columns() -> None:
    a = _Line(("S", "A"), [100.0, 50.0, 20.5], [[90.0, 40.0, 0.0], [110.0, 60.0, 0.0]])
    b = _Line(("S", "B"), [10.0, 0.0], [[9.0, 0.0], [11.0, 0.0]])
    risk = _risk(
        [
            ("S", "A", "bootstrap", DISCOUNTED, 100.0, 150.0, 50.0),
            ("S", "B", "bootstrap", DISCOUNTED, 8.0, 10.0, 2.0),
        ]
    )
    result = SimpleNamespace(lines=(a, b), risk=risk)
    nominal = bridge_table(result, NOMINAL)  # type: ignore[arg-type]
    assert nominal is not None
    assert nominal["heads"] == ["S · A", "S · B", "All lines"]
    steps = dict(nominal["steps"])
    assert steps["Selected unpaid"] == ["171", "10", "181"]
    assert steps["less the origins without simulated development"] == ["-21", "0", "-21"]
    assert steps["plus the difference of the simulation for the other origins"] == ["0", "0", "0"]
    assert steps["Mean of the simulation, nominal"] == ["150", "10", "160"]
    assert nominal["left_out"] == [{"line": "S · A", "origin": "2022", "amount": "21"}]
    discounted = bridge_table(result, DISCOUNTED)  # type: ignore[arg-type]
    assert discounted is not None
    steps = dict(discounted["steps"])
    assert steps["less the discount effect on the simulated mean (RS05)"] == ["-50", "-2", "-52"]
    assert steps["Mean of the simulation, present value"] == ["100", "8", "108"]


def test_a_line_without_a_simulation_shows_dashes_and_no_total() -> None:
    a = _Line(("S", "A"), [100.0], [[100.0]])
    c = _Line(("S", "C"), [5.0], [])
    table = bridge_table(SimpleNamespace(lines=(a, c), risk=_risk([])), NOMINAL)  # type: ignore[arg-type]
    assert table is not None and table["heads"] == ["S · A", "S · C"]
    assert dict(table["steps"])["Mean of the simulation, nominal"] == ["100", "–"]
    only = bridge_table(SimpleNamespace(lines=(c,), risk=_risk([])), NOMINAL)  # type: ignore[arg-type]
    assert only is None


# --- R12: the observed coverage beside every Mack range (record 0753) ---------------------


def _back_test(rows: list[tuple[str, str, str, int, int, int]]) -> dict[str, pl.DataFrame]:
    """(segment, line, method, horizon, origins, inside) of AE02 range calibrations."""
    return {
        "back_test.csv": pl.DataFrame(
            [
                {
                    "segment": a,
                    "line": b,
                    "kind": "range_calibration",
                    "method": m,
                    "horizon_months": h,
                    "origins": n,
                    "inside": k,
                }
                for a, b, m, h, n, k in rows
            ]
            + [
                {
                    "segment": "S",
                    "line": "A",
                    "kind": "summary",
                    "method": "MT06",
                    "horizon_months": 12,
                    "origins": 99,
                    "inside": None,
                }
            ],
            schema_overrides={"inside": pl.Int64},
        )
    }


def test_coverage_pools_the_horizons_of_one_line_and_of_all_lines() -> None:
    from actuarycanary.report import coverage

    tables = _back_test(
        [
            ("S", "A", "MT06", 12, 8, 3),
            ("S", "A", "MT06", 24, 7, 5),
            ("S", "A", "MT11", 12, 8, 8),
            ("S", "B", "MT06", 12, 5, 1),
        ]
    )
    one = coverage.observed(tables, "MT06", "S", "A")
    assert one is not None and (one.inside, one.n) == (8, 15)
    assert coverage.sentence(one) == "90% range; observed coverage in back-test 53.3% (n = 15)"
    everything = coverage.observed(tables, "MT06")
    assert everything is not None and (everything.inside, everything.n) == (9, 20)
    boot = coverage.observed(tables, "MT11", "S", "A")
    assert boot is not None and boot.share == 1.0
    assert coverage.observed(tables, "MT06", "S", "C") is None
    assert coverage.observed({}, "MT06") is None
    assert coverage.sentence(None) == "90% range; no back-test"


def test_the_mack_rows_of_the_uncertainty_page_carry_their_coverage_and_the_others_do_not() -> None:
    tables = _back_test([("S", "A", "MT06", 12, 8, 3), ("S", "A", "MT11", 12, 8, 6)])
    risk = (
        _risk(
            [
                ("S", "A", "mack_lognormal", NOMINAL, 100.0, None, None),
                ("S", "A", "bootstrap", NOMINAL, 100.0, None, None),
                ("S", "A", "expected_cash_flows", NOMINAL, 100.0, None, None),
                ("S", "B", "mack_lognormal", NOMINAL, 50.0, None, None),
            ]
        )
        .with_columns(
            pl.lit(0.0).alias(c)
            for c in ("p50", "p75", "value_at_risk", "tail_value_at_risk", "simulations")
        )
        .with_columns(pl.lit("").alias("label"), pl.lit("").alias("note"))
    )
    shown = {(r["line"], r["source"]): r["coverage"] for r in ranges(risk, NOMINAL, tables)}
    assert shown[("S · A", "Mack, lognormal approximation (RS03)")] == (
        "90% range; observed coverage in back-test 37.5% (n = 8)"
    )
    assert shown[("S · A", "Bootstrap (RS05, MT11)")] == (
        "90% range; observed coverage in back-test 75.0% (n = 8)"
    )
    assert shown[("S · B", "Mack, lognormal approximation (RS03)")] == "90% range; no back-test"
    rows = headline(risk, pl.DataFrame(), NOMINAL, None, tables)
    by_line = {r["line"]: r for r in rows}
    assert by_line["S · A"]["coverage"].endswith("75.0% (n = 8)")  # the bootstrap is chosen
    assert by_line["S · B"]["coverage"] == "90% range; no back-test"


# --- R14: the failed rules beside the data quality score (record 0753) ---------------------


def test_the_quality_page_counts_the_failed_rules_and_says_what_the_score_leaves_out() -> None:
    from actuarycanary.quality.model import QualityReport, RuleScore, Score
    from actuarycanary.report.quality_section import failed_rules, render_quality_section

    def rule(name: str, checked: int, failed: int) -> RuleScore:
        return RuleScore(name, "claims", "validity", "WARNING", 1, ("f",), checked, failed)

    rules = (rule("R1", 100, 0), rule("R2", 100, 6), rule("R3", 50, 14), rule("R4", 10, 0))
    report = QualityReport(None, Score(99.9, 4), {}, {}, {}, rules, (), (), ())
    assert failed_rules(report) == (2, 20)
    html = render_quality_section(report, "1.0.0")
    assert "2 of 4 rules failed on at least one row, pair or claim; 20 failed checks" in html
    assert "not whether they suit reserving" in html
    nothing = QualityReport(None, Score(100.0, 1), {}, {}, {}, (rule("R1", 5, 0),), (), (), ())
    assert failed_rules(nothing) == (0, 0)
    assert "0 of 1 rules failed" in render_quality_section(nothing, "1.0.0")


# --- R17: no severity quantiles for a line whose every family is rejected ------------------


def _severity_tables(why: str) -> dict[str, pl.DataFrame]:
    key = {"segment": "LIFE", "line": "TERM"}
    return {
        "severity_groups.csv": pl.DataFrame([{**key, "claims": 398, "status": "fitted"}]),
        "severity_selected.csv": pl.DataFrame(
            [{**key, "family": "lognormal", "why": why, "claims": 398, "reason": "", "aic": 1.0}]
        ),
        "severity_fits.csv": pl.DataFrame(
            [
                {
                    **key,
                    "family": "lognormal",
                    "aic": 1.0,
                    "bic": 2.0,
                    "ks_p": 0.0,
                    "ad_p": 0.0,
                    "rejected": True,
                    "converged": True,
                    "selected": True,
                }
            ]
        ),
        "severity_quantiles.csv": pl.DataFrame(
            [{**key, "family": "lognormal", "probability": 0.5, "quantile": 3146680.6}]
        ),
    }


def test_a_line_with_every_family_rejected_shows_no_severity_quantiles() -> None:
    from actuarycanary.methods.severity.fitting import NO_FAMILY_FITS, SELECTED_BY_AIC
    from actuarycanary.report.large_loss_section import fits

    rejected = fits(_severity_tables(NO_FAMILY_FITS), "LIFE", "TERM")
    assert rejected["no_fit"] is True
    assert [r["selected"] for r in rejected["rows"]] == [False]  # nothing is "selected"
    kept = fits(_severity_tables(SELECTED_BY_AIC), "LIFE", "TERM")
    assert kept["no_fit"] is False and kept["rows"][0]["selected"] is True
    assert kept["quantiles"][0] == "3,146,681"


# --- R21: histogram axis and phone layout (record 0754) ------------------------------------


def test_the_histogram_axis_is_cut_and_the_caption_names_the_extremes() -> None:
    from actuarycanary.report.uncertainty_section import BINS, histogram

    rng = np.random.default_rng(7)
    body = rng.normal(100.0, 10.0, 9_990)
    sims = np.concatenate([body, [900.0, 1_500.0, 5_000.0, 20_000.0, 90_000.0] * 2])
    distribution = pl.DataFrame({"S / L": sims})
    risk = _risk([("S", "L", "bootstrap", NOMINAL, float(sims.mean()), None, None)]).with_columns(
        pl.lit(float(np.quantile(sims, 0.995))).alias("value_at_risk"),
        pl.lit(float(np.sort(sims)[-100:].mean())).alias("tail_value_at_risk"),
        pl.lit(0.995).alias("var_level"),
        pl.lit(0.99).alias("tvar_level"),
    )
    [(key, figure, caption)] = histogram(risk, distribution, NOMINAL, "TRY")
    low, high = np.quantile(sims, [0.005, 0.995])
    assert figure["layout"]["xaxis"]["range"] == [round(low, 2), round(high, 2)] or (
        figure["layout"]["xaxis"]["range"][0] == pytest.approx(low, abs=0.01)
    )
    counts = figure["data"][0]["y"]
    outside = int(((sims < low) | (sims > high)).sum())
    assert len(counts) == BINS and sum(counts) == sims.size - outside
    assert sum(1 for c in counts if c > 0) >= BINS - 4  # the shape is visible, not two bars
    assert "minimum" in caption and "maximum 90,000" in caption
    assert f"{outside / sims.size:.1%} of the 10,000 simulations are outside" in caption
    assert "Beyond the axis: TVaR 99.0% 2,462" in caption  # the TVaR lies in the extreme draws
    assert len(figure["layout"]["shapes"]) == 2  # mean and VaR are inside the axis
    assert distribution["S / L"].len() == sims.size  # the data stay complete
    assert key == "S-L"


def test_every_table_of_the_page_sits_in_a_scroll_box_and_the_phone_rules_exist(
    default_run: RunResult,
) -> None:
    from html.parser import HTMLParser

    from actuarycanary.report.quality_section import render_quality_section
    from actuarycanary.report.render import render_report

    page = render_report(
        default_run.report_data,
        quality_html=render_quality_section(default_run.quality, "1.0.0"),
    )

    class _Tables(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.stack: list[tuple[str, str]] = []
            self.outside = 0
            self.total = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in {"br", "meta", "link", "img", "input", "hr", "col"}:
                return
            self.stack.append((tag, dict(attrs).get("class") or ""))
            if tag == "table":
                self.total += 1
                if not any("scroll" in c.split() for _, c in self.stack[:-1]):
                    self.outside += 1

        def handle_endtag(self, tag: str) -> None:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    parsed = _Tables()
    parsed.feed(page)
    assert parsed.total > 10 and parsed.outside == 0
    assert "max-width: 1080px" in page and "@media print" in page  # the existing rules stay
    assert "@media screen and (max-width: 640px)" in page
    assert "minmax(min(320px, 100%), 1fr)" in page
