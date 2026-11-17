"""Checks of the life feeds (record 0442): life_in_force (DV-LIF), life_events (DV-LEV) and
fund_flows (DV-FFL). The rules that decide which rows enter a feed are applied by the canonical
step (`canonical/life.py`); the rules here list rows and leave them as they are. What a rule's
action does to the studies (the latest values of a contract, the entry age of the first
valuation, an exit kept, a valuation carried forward, the earliest terminal event) is applied
by the exposure (`life/exposure.py`).
"""

import polars as pl

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.quality.checks import (
    Check,
    Context,
    _frame,
    _outcome,
    _rows,
    in_other,
    references,
)
from actuarycanary.quality.model import Outcome

IN_FORCE, EVENTS, FLOWS = "life_in_force", "life_events", "fund_flows"
EXIT_STATUSES = ("LAPSED", "SURRENDERED", "MATURED", "DEATH_CLAIM", "TRANSFERRED_OUT")
ACTIVE_STATUSES = ("IN_FORCE", "PAID_UP")
TERMINAL_EVENTS = ("DEATH", "SURRENDER", "LAPSE", "MATURITY", "TRANSFER_OUT")
STATUS_OF_EVENT = {
    "DEATH": "DEATH_CLAIM",
    "SURRENDER": "SURRENDERED",
    "LAPSE": "LAPSED",
    "MATURITY": "MATURED",
    "TRANSFER_OUT": "TRANSFERRED_OUT",
}
REINSTATEMENT = "REINSTATEMENT"
SWITCH_TOLERANCE = 0.01  # DV-FFL-06: the legs of a switch agree within a cent
MAX_AGE = 120

NEEDS: dict[str, tuple[str, ...]] = {
    "DV-LEV-04": (IN_FORCE,),
    "DV-LEV-05": (IN_FORCE,),
    "DV-LEV-07": (IN_FORCE,),
    "DV-FFL-05": (IN_FORCE,),
    "DV-FFL-08": (EVENTS,),
}


def _contracts(
    rule: str, concept: str, checked: int, bad: pl.DataFrame, rows: pl.DataFrame, what: str
) -> Outcome:
    """Outcome of a rule about contracts: `bad` holds one row per failing contract, `rows` the
    source rows to point at."""
    failed = bad.height
    shown = ", ".join(bad["contract_id"].head(5).to_list())
    message = f"{failed} of {checked} contracts {what} ({shown})" if failed else ""
    return Outcome(rule, concept, checked, failed, message, references(rows) if failed else ())


def _whole_years(start: pl.Expr, end: pl.Expr) -> pl.Expr:
    """Whole years from `start` to `end` (anniversaries of `start`)."""
    years = end.dt.year() - start.dt.year()
    before = (end.dt.month() * 100 + end.dt.day()) < (start.dt.month() * 100 + start.dt.day())
    return years - before.cast(pl.Int64)


# --- life_in_force -----------------------------------------------------------------------


def same_contract_terms(ctx: Context) -> Outcome | None:  # DV-LIF-06
    frame = _frame(ctx, IN_FORCE, ("contract_id", "entry_date"))
    if frame is None:
        return None
    terms = [c for c in ("entry_date", "product", "sex") if c in frame.columns]
    per = frame.group_by("contract_id").agg(
        pl.any_horizontal(*(pl.col(c).n_unique() > 1 for c in terms)).alias("bad")
    )
    bad = per.filter("bad").sort("contract_id")
    rows = frame.filter(pl.col("contract_id").is_in(bad["contract_id"].implode()))
    what = f"change {', '.join(terms)} between valuations: the latest valuation's are used"
    return _contracts("DV-LIF-06", IN_FORCE, per.height, bad, rows, what)


def _steps(frame: pl.DataFrame) -> pl.DataFrame:
    """Each valuation of a contract next to the previous one."""
    return frame.sort("contract_id", "valuation_date").with_columns(
        pl.col(c).shift(1).over("contract_id").alias(f"prev_{c}")
        for c in ("valuation_date", "age_low", "age_high", "status")
    )


def age_moves_with_time(ctx: Context) -> Outcome | None:  # DV-LIF-07
    """Between two valuations the age band, moved back by the whole years between them, still
    meets the earlier band widened by one year on each side (an open band reaches 120)."""
    frame = _frame(ctx, IN_FORCE, ("contract_id", "valuation_date", "age_low", "age_high"))
    if frame is None:
        return None
    steps = _steps(frame).filter(pl.col("prev_valuation_date").is_not_null())
    years = _whole_years(pl.col("prev_valuation_date"), pl.col("valuation_date"))
    high, prev_high = (pl.col(c).fill_null(MAX_AGE) for c in ("age_high", "prev_age_high"))
    bad = (pl.col("age_low") - years > prev_high + 1) | (high - years < pl.col("prev_age_low") - 1)
    failing = steps.filter(bad.fill_null(False))
    contracts = failing.select("contract_id").unique().sort("contract_id")
    what = "whose age does not move with time: the entry age is taken from the first valuation"
    checked = steps["contract_id"].n_unique()
    return _contracts("DV-LIF-07", IN_FORCE, checked, contracts, failing, what)


def reinstatements(ctx: Context) -> pl.DataFrame:
    """contract_id and event_date of every REINSTATEMENT (empty without life_events)."""
    events = _frame(ctx, EVENTS, ("contract_id", "event_date", "event_type"))
    if events is None:
        return pl.DataFrame(schema={"contract_id": pl.String, "event_date": pl.Date})
    return events.filter(pl.col("event_type") == REINSTATEMENT).select("contract_id", "event_date")


def no_return_without_reinstatement(ctx: Context) -> Outcome | None:  # DV-LIF-08
    frame = _frame(ctx, IN_FORCE, ("contract_id", "valuation_date", "status"))
    if frame is None:
        return None
    ordered = frame.sort("contract_id", "valuation_date").with_columns(
        pl.col("status")
        .is_in(EXIT_STATUSES)
        .cum_max()
        .shift(1, fill_value=False)
        .over("contract_id")
        .alias("left"),
        pl.when(pl.col("status").is_in(EXIT_STATUSES))
        .then(pl.col("valuation_date"))
        .forward_fill()
        .shift(1)
        .over("contract_id")
        .alias("exit_seen"),
    )
    back = ordered.filter(pl.col("left") & pl.col("status").is_in(ACTIVE_STATUSES))
    again = reinstatements(ctx)
    if back.height and again.height:
        excused = (
            back.join(again, on="contract_id")
            .filter((pl.col("event_date") > pl.col("exit_seen")) | pl.col("exit_seen").is_null())
            .filter(pl.col("event_date") <= pl.col("valuation_date"))
            .select(SOURCE_ROW)
        )
        back = back.filter(~pl.col(SOURCE_ROW).is_in(excused[SOURCE_ROW].implode()))
    contracts = back.select("contract_id").unique().sort("contract_id")
    what = (
        "return to IN_FORCE or PAID_UP after an exit without a REINSTATEMENT: the exit is kept, "
        "the later rows leave the exposure"
    )
    return _contracts("DV-LIF-08", IN_FORCE, frame["contract_id"].n_unique(), contracts, back, what)


def valuations_without_gaps(ctx: Context) -> Outcome | None:  # DV-LIF-10
    """A contract has a row at every valuation date of the feed from its first row to its first
    exit status, or to the last valuation date when it never leaves. Rows after an exit are not
    counted (DV-LIF-08 lists them)."""
    frame = _frame(ctx, IN_FORCE, ("contract_id", "valuation_date", "status"))
    if frame is None:
        return None
    dates = frame["valuation_date"].unique().sort()
    leaving = pl.col("status").is_in(EXIT_STATUSES)
    per = frame.group_by("contract_id").agg(
        pl.col("valuation_date").min().alias("first"),
        pl.col("valuation_date").filter(leaving).min().fill_null(dates.max()).alias("end"),
    )
    have = (
        frame.join(per, on="contract_id")
        .filter(pl.col("valuation_date") <= pl.col("end"))
        .group_by("contract_id")
        .agg(pl.col("valuation_date").n_unique().alias("have"))
    )
    first = dates.search_sorted(per["first"], side="left")
    end = dates.search_sorted(per["end"], side="right")
    expected = per.select("contract_id").with_columns(
        pl.Series("expected", end.to_numpy() - first.to_numpy())
    )
    gaps = expected.join(have, on="contract_id").filter(pl.col("have") < pl.col("expected"))
    rows = frame.filter(pl.col("contract_id").is_in(gaps["contract_id"].implode()))
    what = "miss a valuation before their exit: the previous row is carried forward (CV04)"
    return _contracts("DV-LIF-10", IN_FORCE, per.height, gaps.sort("contract_id"), rows, what)


# --- life_events -------------------------------------------------------------------------


def event_within_the_contract(ctx: Context) -> Outcome | None:  # DV-LEV-05
    events = _frame(ctx, EVENTS, ("contract_id", "event_date"))
    in_force = _frame(ctx, IN_FORCE, ("contract_id", "entry_date"))
    if events is None or in_force is None:
        return None
    entry = in_force.group_by("contract_id").agg(pl.col("entry_date").min())
    known = events.join(entry, on="contract_id")
    bad = pl.col("event_date") < pl.col("entry_date")
    if ctx.cut_off is not None:
        bad = bad | (pl.col("event_date") > pl.lit(ctx.cut_off))
    return _outcome("DV-LEV-05", EVENTS, known.height, known.filter(bad))


def _terminal(events: pl.DataFrame) -> pl.DataFrame:
    """Terminal events with the number of REINSTATEMENTs of the contract before them."""
    ordered = events.sort("contract_id", "event_date", SOURCE_ROW).with_columns(
        (pl.col("event_type") == REINSTATEMENT).cum_sum().over("contract_id").alias("spell")
    )
    return ordered.filter(pl.col("event_type").is_in(TERMINAL_EVENTS))


def one_terminal_event(ctx: Context) -> Outcome | None:  # DV-LEV-06
    events = _frame(ctx, EVENTS, ("contract_id", "event_date", "event_type"))
    if events is None:
        return None
    terminal = _terminal(events).with_columns(
        pl.int_range(pl.len()).over("contract_id", "spell").alias("nth")
    )
    return _outcome("DV-LEV-06", EVENTS, terminal.height, terminal.filter(pl.col("nth") > 0))


def status_follows_the_event(ctx: Context) -> Outcome | None:  # DV-LEV-07
    """The status at the first valuation on or after the day the event is known (its
    report_date when given, else its event_date) matches the event, unless a REINSTATEMENT came
    in between."""
    events = _frame(ctx, EVENTS, ("contract_id", "event_date", "event_type"))
    in_force = _frame(ctx, IN_FORCE, ("contract_id", "valuation_date", "status"))
    if events is None or in_force is None:
        return None
    known = (
        pl.max_horizontal("event_date", pl.col("report_date"))
        if "report_date" in events.columns
        else pl.col("event_date")
    )
    terminal = (
        events.filter(pl.col("event_type").is_in(TERMINAL_EVENTS))
        .with_columns(known.alias("known"))
        .sort("known")
    )
    valuations = in_force.select("contract_id", "valuation_date", pl.col("status").alias("seen"))
    pairs = terminal.join_asof(
        valuations.sort("valuation_date"),
        left_on="known",
        right_on="valuation_date",
        by="contract_id",
        strategy="forward",
        check_sortedness=False,
    ).filter(pl.col("valuation_date").is_not_null())
    again = reinstatements(ctx).rename({"event_date": "reinstated"})
    if again.height:
        excused = (
            pairs.join(again, on="contract_id")
            .filter(
                (pl.col("reinstated") >= pl.col("event_date"))
                & (pl.col("reinstated") <= pl.col("valuation_date"))
            )
            .select(SOURCE_ROW)
        )
        pairs = pairs.filter(~pl.col(SOURCE_ROW).is_in(excused[SOURCE_ROW].implode()))
    expected = pl.col("event_type").replace_strict(STATUS_OF_EVENT, return_dtype=pl.String)
    return _outcome("DV-LEV-07", EVENTS, pairs.height, pairs.filter(pl.col("seen") != expected))


# --- fund_flows --------------------------------------------------------------------------


def switches_balance(ctx: Context) -> Outcome | None:  # DV-FFL-06
    frame = _frame(ctx, FLOWS, ("contract_id", "flow_date", "amount", "flow_type"))
    if frame is None:
        return None
    switches = frame.filter(pl.col("flow_type") == "FUND_SWITCH")
    code = pl.col("fund_code") if "fund_code" in frame.columns else pl.lit(None, pl.String)
    groups = (
        switches.with_columns(code.alias("_code"))
        .group_by("contract_id", "flow_date")
        .agg(
            pl.col("amount").sum().alias("total"),
            pl.col("_code").null_count().alias("no_code"),
            pl.col(SOURCE_ROW),
        )
    )
    bad = groups.filter((pl.col("total").abs() > SWITCH_TOLERANCE) | (pl.col("no_code") > 0))
    rows = switches.filter(pl.col(SOURCE_ROW).is_in(bad[SOURCE_ROW].explode().implode()))
    failed = bad.height
    message = (
        f"{failed} of {groups.height} fund switches (a contract on one date) do not sum to zero "
        "or lack a fund_code; kept as given, switches do not enter LF04"
        if failed
        else ""
    )
    return Outcome(
        "DV-FFL-06", FLOWS, groups.height, failed, message, references(rows) if failed else ()
    )


def no_contribution_after_exit(ctx: Context) -> Outcome | None:  # DV-FFL-08
    flows = _frame(ctx, FLOWS, ("contract_id", "flow_date", "flow_type"))
    events = _frame(ctx, EVENTS, ("contract_id", "event_date", "event_type"))
    if flows is None or events is None:
        return None
    contributions = flows.filter(pl.col("flow_type") == "CONTRIBUTION")
    marks = events.filter(pl.col("event_type").is_in((*TERMINAL_EVENTS, REINSTATEMENT))).select(
        "contract_id", "event_date", (pl.col("event_type") != REINSTATEMENT).alias("out")
    )
    # the last terminal event or reinstatement strictly before the flow decides
    last = (
        marks.sort("event_date")
        .group_by("contract_id", "event_date")
        .agg(pl.col("out").last())  # a reinstatement and an exit on one day: as listed last
    )
    state = contributions.sort("flow_date").join_asof(
        last.sort("event_date"),
        left_on="flow_date",
        right_on="event_date",
        by="contract_id",
        strategy="backward",
        allow_exact_matches=False,
        check_sortedness=False,
    )
    return _outcome(
        "DV-FFL-08", FLOWS, contributions.height, state.filter(pl.col("out").fill_null(False))
    )


_POSITIVE = pl.col("amount") > 0
_AMOUNTS = ("sum_assured", "fund_value", "annual_premium", "term_years")


def amounts_not_negative(ctx: Context) -> Outcome | None:  # DV-LIF-09
    frame = ctx.frames.get(IN_FORCE)
    used = [c for c in _AMOUNTS if frame is not None and c in frame.columns]
    if frame is None or not used:
        return None
    bad = pl.any_horizontal(pl.col(c) < 0 for c in used).fill_null(False)
    return _outcome("DV-LIF-09", IN_FORCE, frame.height, frame.filter(bad))


LIFE_CHECKS: dict[str, Check] = {
    "DV-LIF-06": same_contract_terms,
    "DV-LIF-07": age_moves_with_time,
    "DV-LIF-08": no_return_without_reinstatement,
    "DV-LIF-09": amounts_not_negative,
    "DV-LIF-10": valuations_without_gaps,
    "DV-LEV-04": in_other("DV-LEV-04", EVENTS, "contract_id", IN_FORCE),
    "DV-LEV-05": event_within_the_contract,
    "DV-LEV-06": one_terminal_event,
    "DV-LEV-07": status_follows_the_event,
    "DV-LEV-08": _rows(
        "DV-LEV-08",
        EVENTS,
        ("report_date", "event_date"),
        pl.col("report_date") < pl.col("event_date"),
        pl.col("report_date").is_not_null(),
    ),
    "DV-LEV-09": _rows(
        "DV-LEV-09", EVENTS, ("amount",), pl.col("amount") < 0, pl.col("amount").is_not_null()
    ),
    "DV-FFL-05": in_other("DV-FFL-05", FLOWS, "contract_id", IN_FORCE),
    "DV-FFL-06": switches_balance,
    "DV-FFL-07": _rows(
        "DV-FFL-07",
        FLOWS,
        ("amount", "flow_type"),
        ~_POSITIVE,
        pl.col("flow_type") != "FUND_SWITCH",
    ),
    "DV-FFL-08": no_contribution_after_exit,
}
