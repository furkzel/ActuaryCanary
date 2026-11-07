"""MT19 on the claims of a run: the durations, the event rules, the size class at report and the
tables of `run_survival` (records 0616, 0630).

Spec IDs proved: MT19, CL08, CV08. The methods are proved against their fixtures in
tests/methods/survival; these tests prove how the claims become durations.
"""

from datetime import date

from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.survival import analysis as an
from actuarycanary.modules import survival_run
from actuarycanary.modules.survival_run import TABLES, claim_durations, run_survival
from tests.measures.helpers import make_inputs
from tests.quality.builders import claim, cv

CUT_OFF = date(2024, 6, 30)


def _inputs(statuses: dict[str, list[str]], claims: list[dict] | None = None, **extra):
    """Valuations at the end of January onwards, one status per month for each claim."""
    rows = []
    for name, found in statuses.items():
        for month, status in enumerate(found, start=1):
            rows.append(cv(month, claim_id=name, status=status))
    feeds = {"claim_valuations": rows}
    if claims is not None:
        feeds["claims"] = claims
    return make_inputs(feeds, CUT_OFF, **extra)


def _durations(inputs, event: str = "closed") -> dict[str, dict]:
    frame, _ = claim_durations(inputs, event)
    return {row["claim_id"]: row for row in frame.iter_rows(named=True)}


def test_a_closed_claim_runs_from_the_report_date_to_the_close_date_of_the_header() -> None:
    claims = [claim(claim_id="A", report_date=date(2024, 1, 5), close_date=date(2024, 2, 10))]
    found = _durations(
        _inputs({"A": ["OPEN", "CLOSED", "CLOSED", "CLOSED", "CLOSED", "CLOSED"]}, claims)
    )
    assert found["A"]["duration_days"] == 36 and found["A"]["event"] is True
    assert found["A"]["approximate"] is False and found["A"]["report_year"] == 2024


def test_an_open_claim_is_censored_at_the_cut_off() -> None:
    claims = [claim(claim_id="O", report_date=date(2024, 1, 5), close_date=None)]
    found = _durations(_inputs({"O": ["OPEN"] * 6}, claims))
    assert found["O"]["duration_days"] == (CUT_OFF - date(2024, 1, 5)).days
    assert found["O"]["event"] is False and found["O"]["approximate"] is False


def test_a_reopened_claim_has_its_first_closing_as_the_event() -> None:
    """The close date of the header is the last closing (April); the event is February."""
    claims = [claim(claim_id="R", report_date=date(2024, 1, 5), close_date=date(2024, 4, 12))]
    statuses = ["OPEN", "CLOSED", "REOPENED", "CLOSED", "CLOSED", "CLOSED"]
    found = _durations(_inputs({"R": statuses}, claims))
    assert found["R"]["event"] is True
    assert found["R"]["duration_days"] == (date(2024, 2, 29) - date(2024, 1, 5)).days
    assert found["R"]["approximate"] is True  # the first closing is a month-end valuation date


def test_a_claim_reopened_and_open_at_the_cut_off_still_has_its_event() -> None:
    claims = [claim(claim_id="R", report_date=date(2024, 1, 5), close_date=None)]
    statuses = ["OPEN", "CLOSED", "REOPENED", "REOPENED", "REOPENED", "REOPENED"]
    found = _durations(_inputs({"R": statuses}, claims))
    assert found["R"]["event"] is True
    assert found["R"]["duration_days"] == (date(2024, 2, 29) - date(2024, 1, 5)).days


def test_without_claims_the_dates_are_month_ends_of_the_valuations_and_labelled_so() -> None:
    found = _durations(
        _inputs(
            {"A": ["OPEN", "OPEN", "CLOSED", "CLOSED", "CLOSED", "CLOSED"], "B": ["OPEN"] * 6}
        )  # fmt: skip
    )
    assert found["A"]["duration_days"] == (date(2024, 3, 31) - date(2024, 1, 31)).days
    assert found["A"]["event"] is True and found["A"]["approximate"] is True
    assert found["B"]["duration_days"] == (CUT_OFF - date(2024, 1, 31)).days
    assert found["B"]["event"] is False and found["B"]["approximate"] is True
    assert found["A"]["line"] == "UNKNOWN" and found["A"]["segment"] == "UNKNOWN"
    _, information = claim_durations(_inputs({"A": ["OPEN", "CLOSED"] + ["CLOSED"] * 4}))
    assert any("month-end dates" in line for line in information)


def test_a_claim_without_a_close_date_in_the_header_takes_it_from_the_valuations() -> None:
    claims = [claim(claim_id="A", report_date=date(2024, 1, 5), close_date=None)]
    found = _durations(_inputs({"A": ["OPEN", "CLOSED"] + ["CLOSED"] * 4}, claims))
    assert found["A"]["duration_days"] == (date(2024, 2, 29) - date(2024, 1, 5)).days
    assert found["A"]["approximate"] is True


def test_a_nil_closing_is_an_event_unless_the_event_is_a_paid_closing() -> None:
    claims = [
        claim(claim_id="N", report_date=date(2024, 1, 5), close_date=date(2024, 2, 10)),
        claim(claim_id="P", report_date=date(2024, 1, 5), close_date=date(2024, 2, 10)),
    ]
    statuses = {
        "N": ["OPEN", "CLOSED_NIL", "CLOSED_NIL", "CLOSED_NIL", "CLOSED_NIL", "CLOSED_NIL"],
        "P": ["OPEN", "CLOSED", "CLOSED", "CLOSED", "CLOSED", "CLOSED"],
    }
    inputs = _inputs(statuses, claims)
    anyone = _durations(inputs, "closed")
    paid = _durations(inputs, "closed_with_payment")
    assert anyone["N"]["event"] is True and anyone["P"]["event"] is True
    assert paid["N"]["event"] is False and paid["P"]["event"] is True
    assert paid["N"]["duration_days"] == anyone["N"]["duration_days"] == 36  # censored at the nil


def test_a_claim_closed_before_it_was_reported_is_excluded_and_said_so() -> None:
    claims = [
        claim(claim_id="X", report_date=date(2024, 3, 5), close_date=date(2024, 2, 10)),
        claim(claim_id="Y", report_date=date(2024, 1, 5), close_date=date(2024, 2, 10)),
    ]
    statuses = {
        "X": ["OPEN", "CLOSED", "CLOSED", "CLOSED", "CLOSED", "CLOSED"],
        "Y": ["OPEN", "CLOSED", "CLOSED", "CLOSED", "CLOSED", "CLOSED"],
    }
    frame, information = claim_durations(_inputs(statuses, claims))
    assert frame["claim_id"].to_list() == ["Y"]
    assert any(
        "closed before they were reported" in line and "DV-CLM-05" in line for line in information
    )


def test_the_size_class_at_report_is_the_class_of_the_first_valuation_not_of_the_cut_off() -> None:
    claims = [
        claim(claim_id="G", report_date=date(2024, 1, 5), close_date=None),
        claim(claim_id="S", report_date=date(2024, 1, 5), close_date=None),
        claim(claim_id="E", report_date=date(2024, 1, 5), close_date=None, event_code="EQ1"),
    ]
    rows = []
    for name in ("G", "S", "E"):
        for month in range(1, 7):
            # G grows from 10 to 500 incurred, S stays at 10; the threshold is 100
            paid = 500.0 if name == "G" and month >= 3 else 0.0
            reserve = 10.0 if not (name == "G" and month >= 3) else 0.0
            rows.append(cv(month, claim_id=name, paid_to_date=paid, case_reserve=reserve))
    inputs = make_inputs(
        {"claim_valuations": rows, "claims": claims},
        CUT_OFF,
        large_loss_thresholds={("UNKNOWN", "UNKNOWN"): 100.0},
    )
    found = _durations(inputs)
    assert found["G"]["size_class_at_report"] == "ATTRITIONAL"
    assert found["G"]["size_class_at_cutoff"] == "LARGE"  # depends on the outcome: description only
    assert found["S"]["size_class_at_report"] == found["S"]["size_class_at_cutoff"] == "ATTRITIONAL"
    assert found["E"]["size_class_at_report"] == found["E"]["size_class_at_cutoff"] == "CATASTROPHE"


def test_a_claim_that_is_large_at_its_first_valuation_is_large_at_report() -> None:
    claims = [claim(claim_id="L", report_date=date(2024, 1, 5), close_date=None)]
    rows = [cv(m, claim_id="L", paid_to_date=0.0, case_reserve=900.0) for m in range(1, 7)]
    inputs = make_inputs(
        {"claim_valuations": rows, "claims": claims},
        CUT_OFF,
        large_loss_thresholds={("UNKNOWN", "UNKNOWN"): 100.0},
    )
    assert _durations(inputs)["L"]["size_class_at_report"] == "LARGE"


# ------------------------------------------------------------------ the run


def _many(n: int = 60):
    """n claims on two lines, closing after 30 to 150 days; the FAST line closes sooner."""
    claims, statuses = [], {}
    for i in range(n):
        name = f"C{i:03d}"
        fast = i % 2 == 0
        report = date(2024, 1, 2)
        months_open = 1 + (i % 3) + (0 if fast else 2)
        claims.append(
            claim(
                claim_id=name, report_date=report, close_date=None,
                line="FAST" if fast else "SLOW", segment="S",
            )
        )  # fmt: skip
        statuses[name] = ["OPEN"] * months_open + ["CLOSED"] * (6 - months_open)
    return _inputs(statuses, claims)


def test_run_survival_writes_every_table_and_names_the_entries_in_force() -> None:
    run = run_survival(_many(), AssumptionsRegister())
    assert run.ran == ("MT19",) and not run.reason
    assert set(run.tables) == set(TABLES)
    assert set(run.files()) == set(TABLES.values())
    assert run.tables["groups"].height > 0 and run.tables["curves"].height > 0
    assert {e.name for e in run.entries} == {
        "event",
        "covariates",
        "ties",
        "confidence",
        "time_unit",
    }
    assert {e.scope for e in run.entries} == {"S/survival"}
    model = run.tables["models"].row(0, named=True)
    assert model["segment"] == "S" and model["covariates"] == "line"


def test_a_segment_without_a_cox_model_is_listed_in_the_notes_of_the_module() -> None:
    run = run_survival(
        _many(30), AssumptionsRegister()
    )  # 30 claims: under 20 events? no, 30 events
    assert run.tables["models"]["status"].to_list() == ["fitted"]
    few = run_survival(_many(14), AssumptionsRegister())
    assert few.tables["models"]["status"].to_list() == ["not run"]
    assert any(
        "no Cox model for S" in line and "fewer than 20" in line for line in few.notes["M03"]
    )
    assert any(d.code == "NO_COX_MODEL" for d in few.diagnostics)


def test_the_register_chooses_the_ties_and_the_event_of_a_segment() -> None:
    entries = (
        Assumption(method="MT19", name="ties", scope="S/survival", value="breslow",
                   who="analyst", why="test"),
        Assumption(method="MT19", name="event", scope="S/survival", value="closed_with_payment",
                   who="analyst", why="test"),
    )  # fmt: skip
    run = run_survival(_many(), AssumptionsRegister(entries=entries))
    assert run.tables["models"]["ties"].to_list() == ["breslow"]
    by_name = {e.name: e for e in run.entries}
    assert by_name["event"].value == "closed_with_payment" and by_name["event"].who == "analyst"


def test_without_valuations_the_run_says_why() -> None:
    inputs = make_inputs({"claim_valuations": [cv(1)]}, CUT_OFF)
    empty = type(inputs)({}, inputs.cut_off, inputs.reporting_currency, inputs.rates, inputs.market)
    run = run_survival(empty, AssumptionsRegister())
    assert run.reason == "no claim valuations were loaded" and run.ran == () and not run.files()


def test_diagnostic_rows_have_the_columns_of_diagnostics_csv() -> None:
    run = run_survival(_many(14), AssumptionsRegister())
    rows = survival_run.diagnostic_rows(run)
    assert rows and all(
        set(r)
        == {
            "segment",
            "line",
            "measure",
            "method",
            "code",
            "severity",
            "target",
            "value",
            "message",
        }
        for r in rows
    )
    assert {r["measure"] for r in rows} == {"survival"} and {r["method"] for r in rows} == {"MT19"}


def test_the_settings_hold_every_default_and_no_seed() -> None:
    settings = survival_run.settings()["MT19"]
    assert settings["event"] == "closed" and settings["covariates"] == ["line"]
    assert settings["ties"] == "efron" and settings["confidence"] == 0.95
    assert settings["time_unit"] == "days" and settings["min_events"] == an.MIN_EVENTS == 20
    assert "seed" not in settings and "seed" not in survival_run.settings()
    assert settings["percentiles"] == [0.25, 0.5, 0.75]
