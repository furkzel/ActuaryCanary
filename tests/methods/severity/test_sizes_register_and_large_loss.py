"""The claim-size frame of MT17 and MT18, the assumptions register for both, and the large_loss
section of project.yaml with its effect on the CV08 classes (record 0601).

Spec IDs proved: MT17, MT18 (register and seeds), CV08 (override).
"""

from datetime import date

import numpy as np
import polars as pl
import pytest

from actuarycanary.measures.claim_base import ATTRITIONAL, LARGE, size_classes
from actuarycanary.measures.model import MeasureRequest
from actuarycanary.methods.assumptions import Assumption, AssumptionError, AssumptionsRegister
from actuarycanary.methods.severity import (
    LargeLossError,
    group_sizes,
    mt17_judged,
    mt18_judged,
    parse_large_loss,
)
from actuarycanary.methods.severity.sizes import group_rng, severity_trend
from tests.measures.helpers import make_inputs
from tests.methods.severity.helpers import CLOSED, NIL, OPEN, sizes_frame
from tests.quality.builders import claim, cv

# ------------------------------------------------------------------ sizes


def test_nil_claims_and_zero_sizes_are_never_used() -> None:
    frame = pl.concat(
        [
            sizes_frame([10.0, 20.0], status=CLOSED, prefix="A"),
            sizes_frame([0.0, 5.0], status=[NIL, CLOSED], prefix="B"),
            sizes_frame([30.0], status=OPEN, prefix="C"),
        ]
    )
    closed = group_sizes(frame, claims_used="closed")
    everything = group_sizes(frame, claims_used="all_non_nil")
    assert closed[0].sizes.tolist() == [10.0, 20.0, 5.0]
    assert everything[0].sizes.tolist() == [10.0, 20.0, 5.0, 30.0]


def test_missing_segment_and_line_are_unknown_and_groups_are_sorted() -> None:
    frame = sizes_frame([1.0, 2.0, 3.0]).drop("segment", "line")
    assert [g.key for g in group_sizes(frame)] == [("UNKNOWN", "UNKNOWN")]
    two = pl.concat(
        [sizes_frame([1.0], line="B", prefix="X"), sizes_frame([2.0], line="A", prefix="Y")]
    )
    assert [g.label for g in group_sizes(two)] == ["S / A", "S / B"]


def test_catastrophe_claims_are_dropped_kept_or_made_one_size_per_event() -> None:
    frame = sizes_frame(
        [100.0, 200.0, 301.0, 5.0, 7.0],
        event_codes=["E1", "E1", "E2", None, None],
        years=[2020, 2021, 2022, 2020, 2021],
    )
    assert group_sizes(frame, catastrophes="exclude")[0].sizes.tolist() == [5.0, 7.0]
    assert group_sizes(frame, catastrophes="keep")[0].sizes.tolist() == [
        100.0,
        200.0,
        301.0,
        5.0,
        7.0,
    ]
    events = group_sizes(frame, catastrophes="events")[0]
    assert sorted(events.sizes.tolist()) == [5.0, 7.0, 300.0, 301.0]  # E1 = 100 + 200
    assert events.n_events == 2
    years = dict(zip(events.sizes.tolist(), events.years.tolist(), strict=True))
    assert years[300.0] == 2020.0  # an event takes the earliest year of its claims
    assert years[301.0] == 2022.0


def test_unknown_options_are_refused() -> None:
    frame = sizes_frame([1.0])
    with pytest.raises(ValueError, match="claims_used"):
        group_sizes(frame, claims_used="open")
    with pytest.raises(ValueError, match="catastrophes"):
        group_sizes(frame, catastrophes="drop")
    with pytest.raises(ValueError, match="column 'size'"):
        group_sizes(frame.drop("size"))


def test_group_generators_depend_on_seed_group_and_purpose_only() -> None:
    first = group_rng(1, ("S", "L"), 3).random(3)
    assert group_rng(1, ("S", "L"), 3).random(3).tolist() == first.tolist()
    assert group_rng(2, ("S", "L"), 3).random(3).tolist() != first.tolist()
    assert group_rng(1, ("S", "M"), 3).random(3).tolist() != first.tolist()
    assert group_rng(1, ("S", "L"), 4).random(3).tolist() != first.tolist()


def test_trend_of_sizes_by_year_is_the_log_linear_slope() -> None:
    years = np.repeat([2020.0, 2021.0, 2022.0, 2023.0], 5)
    sizes = 1000.0 * 1.10 ** (years - 2020.0)
    table, summary = severity_trend(sizes, years)
    assert table["origin_year"].to_list() == [2020, 2021, 2022, 2023]
    assert table["claims"].to_list() == [5, 5, 5, 5]
    assert table["mean"][1] == pytest.approx(1100.0)
    assert summary["annual_change"] == pytest.approx(0.10, rel=1e-9)
    assert summary["p_value"] == pytest.approx(0.0, abs=1e-9)
    _, flat = severity_trend(sizes[:5], years[:5])  # one year: no trend
    assert np.isnan(flat["annual_change"])


# ------------------------------------------------------------------ register


def _register(*entries: Assumption) -> AssumptionsRegister:
    return AssumptionsRegister(entries=entries)


def _entry(method: str, name: str, value, scope: str = "*", target: str = "") -> Assumption:
    return Assumption(
        method=method, name=name, scope=scope, target=target, value=value,
        who="owner", when=date(2026, 10, 25), why="reviewed with the claims team",
    )  # fmt: skip


def test_without_entries_mt17_runs_on_the_specification_defaults() -> None:
    options, entries = mt17_judged(_register(), "NON_LIFE/MOTOR_TPL/severity")
    assert options == {
        "claims_used": "closed",
        "truncation_point": 0.0,
        "exclude_catastrophes": True,
        "significance": 0.05,
        "limits": [],
    }
    assert {e.name for e in entries} == {
        "claims_used", "truncation_point", "exclude_catastrophes", "significance",
    }  # fmt: skip
    assert all(e.is_default and e.value == e.default for e in entries)


def test_a_user_entry_replaces_the_default_and_keeps_who_when_and_why() -> None:
    scope = "NON_LIFE/MOTOR_TPL/severity"
    register = _register(
        _entry("MT17", "claims_used", "all_non_nil", scope),
        _entry("MT17", "truncation_point", 2500, scope),
        _entry("MT17", "limit", 100000, scope, target="100000"),
        _entry("MT17", "limit", 500000, scope, target="500000"),
    )
    options, entries = mt17_judged(register, scope)
    assert options["claims_used"] == "all_non_nil" and options["truncation_point"] == 2500.0
    assert options["limits"] == [100000.0, 500000.0]
    by_name = {(e.name, e.target): e for e in entries}
    chosen = by_name[("claims_used", "")]
    assert (chosen.who, chosen.when, chosen.default) == ("owner", date(2026, 10, 25), "closed")
    assert chosen.why == "reviewed with the claims team"
    assert by_name[("limit", "500000")].value == 500000.0
    # another scope is untouched
    other, _ = mt17_judged(register, "NON_LIFE/MOTOR_OD/severity")
    assert other["claims_used"] == "closed" and other["limits"] == []


def test_a_value_passed_by_the_run_is_labelled_a_run_setting() -> None:
    options, entries = mt17_judged(_register(), "s", claims_used="all_non_nil", significance=0.01)
    assert options["claims_used"] == "all_non_nil"
    who = {e.name: e.who for e in entries}
    assert who["claims_used"] == who["significance"] == "run settings"
    assert who["truncation_point"] == "default"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("claims_used", "open", "claims_used"),
        ("truncation_point", -1, "negative"),
        ("truncation_point", "high", "not a number"),
        ("exclude_catastrophes", "yes", "true or false"),
        ("significance", 1.5, "between 0 and 1"),
        ("limit", -5, "positive"),
    ],
)
def test_malformed_mt17_entries_are_refused(name: str, value, message: str) -> None:
    with pytest.raises(AssumptionError, match=message):
        mt17_judged(
            _register(_entry("MT17", name, value, target="x" if name == "limit" else "")), "s"
        )


def test_mt18_register_entries_and_their_checks() -> None:
    options, entries = mt18_judged(
        _register(_entry("MT18", "fdr_level", 0.05), _entry("MT18", "min_exceedances", 80)), "s"
    )
    assert options == {"claims_used": "all_non_nil", "fdr_level": 0.05, "min_exceedances": 80}
    assert {e.name: e.default for e in entries} == {
        "claims_used": "all_non_nil", "fdr_level": 0.10, "min_exceedances": 50,
    }  # fmt: skip
    for name, value in (("fdr_level", 0), ("min_exceedances", 5), ("min_exceedances", 60.5)):
        with pytest.raises(AssumptionError):
            mt18_judged(_register(_entry("MT18", name, value)), "s")


# ------------------------------------------------------------------ large_loss in project.yaml


def test_no_large_loss_section_means_the_cv08_defaults() -> None:
    for section in (None, {}):
        settings = parse_large_loss(section)
        assert settings.percentile == 0.99 and dict(settings.thresholds) == {}
        assert settings.manifest_record() == {
            "percentile": 0.99,
            "thresholds": {},
            "source": "default",
        }


def test_the_section_is_read_and_its_values_in_force_go_to_the_manifest() -> None:
    settings = parse_large_loss(
        {"percentile": 0.95, "thresholds": {"NON_LIFE/MOTOR_TPL": 250000, "LIFE/TERM": 1e6}}
    )
    assert settings.percentile == 0.95
    assert dict(settings.thresholds) == {("NON_LIFE", "MOTOR_TPL"): 250000.0, ("LIFE", "TERM"): 1e6}
    assert settings.manifest_record() == {
        "percentile": 0.95,
        "thresholds": {"LIFE/TERM": 1e6, "NON_LIFE/MOTOR_TPL": 250000.0},
        "source": "project.yaml",
    }


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("0.95", "mapping"),
        ({"percentil": 0.95}, "unknown key percentil"),
        ({"percentile": 1.0}, "between 0 and 1"),
        ({"percentile": True}, "not a number"),
        ({"thresholds": {"MOTOR_TPL": 5}}, "SEGMENT/LINE"),
        ({"thresholds": {"NON_LIFE/": 5}}, "SEGMENT/LINE"),
        ({"thresholds": {"NON_LIFE/MOTOR": 0}}, "above zero"),
        ({"thresholds": {"NON_LIFE/MOTOR": "big"}}, "not a number"),
        ({"thresholds": [5]}, "SEGMENT/LINE to an amount"),
    ],
)
def test_malformed_large_loss_sections_are_refused(section, message: str) -> None:
    with pytest.raises(LargeLossError, match=message):
        parse_large_loss(section)


def _classes(settings) -> dict[str, str]:
    """CV08 classes of 150 claims of sizes 1..150 in S / L under the given settings."""
    rows = [
        cv(1, claim_id=f"K{i:03d}", paid_to_date=float(i), case_reserve=0.0, status="CLOSED")
        for i in range(1, 151)
    ]
    claims = [claim(claim_id=f"K{i:03d}", segment="S", line="L") for i in range(1, 151)]
    inputs = make_inputs(
        {"claim_valuations": rows, "claims": claims},
        large_loss_percentile=settings.percentile,
        large_loss_thresholds=dict(settings.thresholds),
    )
    frame, _ = size_classes(inputs, MeasureRequest())
    return dict(zip(frame["claim_id"], frame["claim_size_class"], strict=True))


def test_a_fixed_threshold_and_a_percentile_change_the_large_class() -> None:
    default = _classes(parse_large_loss(None))
    # the 99th percentile of 1..150 is 1 + 0.99 x 149 = 148.51: the two largest claims
    assert {k for k, v in default.items() if v == LARGE} == {"K149", "K150"}
    fixed = _classes(parse_large_loss({"thresholds": {"S/L": 100}}))
    assert sum(v == LARGE for v in fixed.values()) == 51  # sizes 100 to 150
    assert fixed["K099"] == ATTRITIONAL and fixed["K100"] == LARGE
    lower = _classes(parse_large_loss({"percentile": 0.90}))
    assert sum(v == LARGE for v in lower.values()) == 15  # 1 + 0.9 x 149 = 135.1: sizes 136 to 150
    both = _classes(parse_large_loss({"percentile": 0.90, "thresholds": {"S/L": 100}}))
    assert both == fixed  # a fixed amount replaces the percentile for its group
