"""Status marks of M07 (recoveries) and M09 (expenses) from the loaded concepts, by the
`required_all` and `required_any` of their own specifications. The marks are worked out on the
catalogue that holds both modules, whether or not they are built yet."""

from typing import Any

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.quality.engine import evaluate
from actuarycanary.spec.loader import load_specs
from tests.quality.builders import Rows, cv, expense, frames, recovery

ALL = load_specs(planned=True)


def _status(rows: Rows, blocked: dict[str, tuple[Any, ...]] | None = None) -> dict[str, Any]:
    built = frames(rows)
    feeds = {
        c: CanonicalFeed(
            c,
            "1",
            f,
            tuple(x for x in f.columns if not x.startswith("_")),
            (blocked or {}).get(c, ()),
        )
        for c, f in built.items()
    }
    return {m.module: m for m in evaluate(ALL, feeds, built).modules}


def test_the_specifications_state_the_requirements() -> None:
    m07, m09 = ALL.modules["M07"], ALL.modules["M09"]
    assert (m07.required_all, m07.required_any) == ([], ["recoveries", "claim_valuations"])
    assert (m09.required_all, m09.required_any) == (["expenses"], [])


def test_m07_is_able_on_claim_valuations_alone_and_on_recoveries() -> None:
    assert _status({"claim_valuations": [cv()]})["M07"].status == "ok"
    both = {"claim_valuations": [cv()], "recoveries": [recovery()]}
    assert _status(both)["M07"].status == "ok"


def test_m09_is_able_on_expenses_alone_and_unable_without_them() -> None:
    assert _status({"claim_valuations": [cv()], "expenses": [expense()]})["M09"].status == "ok"
    without = _status({"claim_valuations": [cv()]})["M09"]
    assert without.status == "unable"
    assert without.reasons == (ALL.modules["M09"].skip_reason,)
    assert without.reasons[0].startswith("Expenses did not run: no expenses were loaded.")


def test_a_blocking_finding_on_a_required_field_limits_or_stops_the_module() -> None:
    from actuarycanary.canonical.feeds import Finding

    keyless = Finding("expenses", "DV-EXP-01", "BLOCKING", 1, "rows without period excluded", (2,))
    rows = {"claim_valuations": [cv()], "expenses": [expense(), expense(period=None)]}
    marked = _status(rows, {"expenses": (keyless,)})["M09"]
    assert marked.status in ("limited", "unable") and "DV-EXP-01" in marked.reasons[0]
    assert marked.status == "unable"  # period is required by the measures of the module


def test_m10_gets_no_mark_and_m08_is_unable_without_treaties() -> None:
    marks = {m.module: m for m in evaluate(load_specs(), {}, {}).modules}
    assert "M10" not in marks
    assert marks["M08"].status == "unable"  # built by F2a; reinsurance_treaties is required
