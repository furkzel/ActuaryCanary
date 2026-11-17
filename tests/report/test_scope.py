"""The scope guard (record 0815): every table and headline of the report model states its scope,
and no table cut by segment adds segments. The run is the tiny baseline (LIFE and NON_LIFE);
the M08 page is checked on a hand-built book of two segments, because the tiny baseline has no
treaties.

Spec IDs proved: RP01, M07, M08, M09.
"""

from dataclasses import replace

import polars as pl
import pytest

from actuarycanary.pipeline import RunResult
from actuarycanary.report import scope
from tests.report.scope_guard import check, check_model


def test_every_table_of_the_report_states_its_scope(default_run: RunResult) -> None:
    model = default_run.report_data
    assert {t["segment"] for t in model["tiles"]} == {"LIFE", "NON_LIFE"}
    assert {p["module"] for p in model["pages"]} >= {"M07", "M09"}
    assert check_model(model) == []


def test_a_table_without_a_declaration_fails() -> None:
    body = {"rows": [{"line": "LIFE · X"}], "other": [{"a": 1}], "scopes": {}}
    found = check(body, {"LIFE", "NON_LIFE"}, "page")
    assert [p.split(" has")[0] for p in found] == ["page: table rows", "page: table other"]


def test_a_segment_table_that_adds_segments_fails() -> None:
    declared = {"rows": scope.declare("Ratios", scope.SEGMENT)}
    segments = {"LIFE", "NON_LIFE"}
    good = {"rows": [{"segment": "LIFE"}, {"line": "NON_LIFE · M"}], "scopes": declared}
    assert check(good, segments, "page") == []
    mixed = {"rows": [{"line": "LIFE · X / NON_LIFE · Y"}], "scopes": declared}
    assert "mixes segments" in check(mixed, segments, "page")[0]
    total = {"rows": [{"line": "All lines"}], "scopes": declared}
    assert "names no segment" in check(total, segments, "page")[0]
    nested = {"rows": [{"line": "LIFE · X", "rows": [{"origin": "2024"}]}], "scopes": declared}
    assert check(nested, segments, "page") == []  # a nested row inherits the segment of its line


def test_a_company_table_must_say_so_and_the_level_must_be_known() -> None:
    body = {"rows": [{"a": 1}], "scopes": {"rows": {"level": "company", "label": ""}}}
    assert "without a label" in check(body, set(), "page")[0]
    body["scopes"] = {"rows": {"level": "world", "label": "x"}}
    assert "unknown level" in check(body, set(), "page")[0]
    with pytest.raises(ValueError):
        scope.declare("x", "world")


# --- M08 on a book of two segments ---------------------------------------------------------


def _two_segment_book():
    """2024, one origin year, two segments with different ratios (all amounts in TRY).

    NON_LIFE / L: gross incurred 300, ceded 90, written premium 2000, ceded premium 600,
    commission 120, reinstatement premium 10. LIFE / M: gross incurred 500, ceded 200, written
    premium 1000, ceded premium 500, commission 50, no reinstatement."""
    from datetime import date

    from tests.measures.helpers import make_inputs
    from tests.quality.builders import claim, cv, policy, premium

    year = {"inception_date": date(2024, 1, 1), "expiry_date": date(2025, 1, 1), "currency": "TRY"}
    book = (
        # (claim, policy, segment, line, paid, reserve, ceded paid, ceded reserve, written, ceded,
        #  commission)
        ("F", "P1", "NON_LIFE", "L", 200.0, 100.0, 60.0, 30.0, 2000.0, 600.0, 120.0),
        ("G", "P2", "LIFE", "M", 400.0, 100.0, 150.0, 50.0, 1000.0, 500.0, 50.0),
    )
    rows = {
        "claim_valuations": [
            cv(
                12,
                claim_id=c,
                paid_to_date=pd,
                case_reserve=pr,
                ceded_paid_to_date=cp,
                ceded_reserve=cr,
            )
            for c, _, _, _, pd, pr, cp, cr, _, _, _ in book
        ],
        "claims": [
            claim(
                claim_id=c,
                occurrence_date=date(2024, 6, 1),
                report_date=date(2024, 6, 2),
                close_date=None,
                line=line,
                segment=seg,
                policy_id=p,
            )
            for c, p, seg, line, *_ in book
        ],
        "policies": [
            policy(
                policy_id=p,
                start_date=date(2024, 1, 1),
                end_date=date(2025, 1, 1),
                segment=seg,
                line=line,
            )
            for _, p, seg, line, *_ in book
        ],
        "premiums": [
            premium(
                transaction_id=f"{kind}{p}",
                policy_id=p,
                booking_date=date(2024, 1, 1),
                amount=a,
                type=t,
            )
            for _, p, _, _, _, _, _, _, w, c, k in book
            for kind, t, a in (
                ("W", "WRITTEN", w),
                ("C", "CEDED_PREMIUM", c),
                ("K", "RI_COMMISSION", k),
            )
        ],
        "reinsurance_treaties": [
            {
                "treaty_id": "QSL",
                "treaty_type": "QUOTA_SHARE",
                "line": "L",
                "cession_share": 0.3,
                **year,
            },
            {
                "treaty_id": "QSM",
                "treaty_type": "QUOTA_SHARE",
                "line": "M",
                "cession_share": 0.4,
                **year,
            },
        ],
        "reinsurance_transactions": [
            {
                "transaction_id": "R1",
                "treaty_id": "QSL",
                "booking_date": date(2024, 12, 31),
                "amount": 10.0,
                "currency": "TRY",
                "type": "REINSTATEMENT_PREMIUM",
            }
        ],
    }
    return make_inputs(rows, cut_off=date(2024, 12, 31))


def test_ri04_by_segment_adds_up_to_the_programme_and_never_mixes_segments() -> None:
    from actuarycanary.convert.bases import ReinsuranceBasis
    from tests.measures.helpers import measure

    inputs = _two_segment_book()
    by_segment = measure(
        inputs, "RI04", "segment", "origin_period", reinsurance=ReinsuranceBasis.CEDED
    )
    assert by_segment.frame is not None, by_segment.reason
    got = {r["segment"]: r for r in by_segment.frame.iter_rows(named=True)}
    # (ceded incurred + commission - ceded premium - reinstatement premium) / gross earned
    assert got["NON_LIFE"]["value"] == pytest.approx((90 + 120 - 600 - 10) / 2000)
    assert got["NON_LIFE"]["reinstatement_premium"] == pytest.approx(10.0)
    assert got["LIFE"]["value"] == pytest.approx((200 + 50 - 500) / 1000)
    assert got["LIFE"]["reinstatement_premium"] == pytest.approx(0.0)
    whole = measure(inputs, "RI04", "origin_period", reinsurance=ReinsuranceBasis.CEDED)
    assert whole.frame is not None
    (programme,) = whole.frame.iter_rows(named=True)
    assert programme["numerator"] == pytest.approx(
        got["NON_LIFE"]["numerator"] + got["LIFE"]["numerator"]
    )
    assert programme["value"] == pytest.approx((290 + 170 - 1100 - 10) / 3000)


def test_the_m08_page_shows_the_loss_ratios_of_each_segment_by_hand() -> None:
    from actuarycanary.modules.reinsurance import reinsurance_run
    from actuarycanary.report.reinsurance_section import reinsurance_page
    from tests.report.test_pages_m07_m09 import analysis_of

    inputs = _two_segment_book()
    body = reinsurance_page(
        analysis_of(inputs), reinsurance_run(inputs), None, lambda *ids: ", ".join(ids), "TRY"
    )
    rows = {r["segment"]: r for r in body["origins"] if r["origin"] == "2024"}
    # gross, ceded and net incurred over the gross earned premium of the segment
    assert (rows["NON_LIFE"]["gross"], rows["NON_LIFE"]["ceded"], rows["NON_LIFE"]["net"]) == (
        "15.0%",
        "4.5%",
        "10.5%",
    )
    assert (rows["LIFE"]["gross"], rows["LIFE"]["ceded"], rows["LIFE"]["net"]) == (
        "50.0%",
        "20.0%",
        "30.0%",
    )
    assert rows["NON_LIFE"]["ri04"] == "-20.0%" and rows["LIFE"]["ri04"] == "-25.0%"
    shares = {r["segment"]: r for r in body["shares"]}
    assert set(shares) == {"LIFE", "NON_LIFE"}
    assert check(body, {"LIFE", "NON_LIFE"}, "M08") == []
    assert [k for k, v in body["scopes"].items() if v["level"] == "company"] == [
        "treaties",
        "programmes",
        "allocation",
        "reconciliation",
    ]


def test_the_m08_page_says_in_turkish_what_is_company_level() -> None:
    from actuarycanary.modules.reinsurance import reinsurance_run
    from actuarycanary.report import language
    from actuarycanary.report.reinsurance_section import reinsurance_page
    from tests.report.test_pages_m07_m09 import analysis_of

    inputs = _two_segment_book()
    with language.using("tr"), language.recording() as asked:
        body = reinsurance_page(
            analysis_of(inputs), reinsurance_run(inputs), None, lambda *ids: ", ".join(ids), "TRY"
        )
    assert language.untranslated(asked) == []
    label = body["scopes"]["treaties"]["label"]
    assert label == "şirket düzeyinde kaydedilmiştir, tüm bölümler birlikte"


def test_ri04_by_segment_stops_when_a_line_belongs_to_two_segments() -> None:
    """The reinstatement premium reaches a segment through the line it was allocated to; a line
    named under two segments cannot be split, so the figure is not computed (not guessed)."""
    from actuarycanary.convert.bases import ReinsuranceBasis
    from tests.measures.helpers import measure

    inputs = _two_segment_book()
    claims = inputs.feeds["claims"].with_columns(line=pl.lit("L"))
    ambiguous = replace(inputs, feeds={**inputs.feeds, "claims": claims})
    result = measure(
        ambiguous, "RI04", "segment", "origin_period", reinsurance=ReinsuranceBasis.CEDED
    )
    assert result.frame is None and "no single segment" in (result.reason or "")
