"""Injected data faults, so that quality checks and anomaly flags can be scored.

Faults change the data files only. The truth (ultimates, patterns) is the world as simulated,
before any fault. Each fault is recorded with the row it lands on in the final table.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from actuarycanary.synthetic.claims import ClaimWorld
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.scenario import Scenario, SizeSpec

UNKNOWN_STATUS_LABELS = ("BILINMIYOR", "???", "X9", "TBD", "PEND-REV")


@dataclass(frozen=True)
class Fault:
    fault_type: str
    file: str
    key: str  # claim_id|valuation_date, claim_id or transaction_id
    row: int  # 0-based data row in the final canonical table
    detail: str


def _count(base: int, size: SizeSpec) -> int:
    return 0 if base == 0 else max(1, round(base * size.fault_scale))


def _insert_duplicates(frame: pl.DataFrame, pick: np.ndarray) -> tuple[pl.DataFrame, np.ndarray]:
    """Repeat rows `pick` right after themselves; return the frame and each original's new row."""
    copies = np.ones(frame.height, dtype=np.int64)
    copies[pick] = 2
    index = np.repeat(np.arange(frame.height), copies)
    new_row = np.cumsum(copies) - copies
    return frame[index], new_row


def inject_faults(
    scenario: Scenario,
    size: SizeSpec,
    frames: dict[str, pl.DataFrame],
    world: ClaimWorld,
    streams: Streams,
) -> tuple[dict[str, pl.DataFrame], list[Fault]]:
    spec = scenario.injected_faults
    rng = streams.get("faults")
    faults: list[Fault] = []
    out = dict(frames)

    # --- claims: report date before the occurrence date --------------------------------
    claims = frames["claims"]
    n_report = min(_count(spec.report_before_occurrence, size), claims.height)
    chosen = np.sort(rng.choice(claims.height, n_report, replace=False))
    report = claims["report_date"].to_numpy().astype("datetime64[D]").copy()
    occurrence = claims["occurrence_date"].to_numpy().astype("datetime64[D]")
    report[chosen] = occurrence[chosen] - rng.integers(1, 31, n_report).astype("timedelta64[D]")
    claims = claims.with_columns(pl.Series("report_date", report).cast(pl.Date))
    ids = claims["claim_id"].to_list()
    faults += [
        Fault(
            "report_before_occurrence",
            "claims",
            ids[i],
            int(i),
            f"report {report[i]} before occurrence {occurrence[i]}",
        )
        for i in chosen
    ]
    out["claims"] = claims

    # --- claim_valuations ------------------------------------------------------------------
    valuations = frames["claim_valuations"]
    n = valuations.height
    claim = np.array(valuations["claim_id"].to_list(), dtype=object)
    vdate = valuations["valuation_date"].to_numpy().astype("datetime64[D]")
    paid = valuations["paid_to_date"].to_numpy().copy()
    ceded_paid = valuations["ceded_paid_to_date"].to_numpy().copy()
    status = np.array(valuations["status"].to_list(), dtype=object)
    currency = np.array(valuations["currency"].to_list(), dtype=object)
    recovered = (
        valuations["subrogation_to_date"].to_numpy() + valuations["salvage_to_date"].to_numpy()
    ) > 0

    order = np.lexsort((vdate, claim))  # rows grouped by claim, in date order
    previous = np.full(n, -1, dtype=np.int64)
    same = claim[order][1:] == claim[order][:-1]
    previous[order[1:][same]] = order[:-1][same]
    increase = np.zeros(n)
    has_previous = previous >= 0
    increase[has_previous] = paid[has_previous] - paid[previous[has_previous]]

    used_rows = np.zeros(n, dtype=bool)
    used_claims: set[str] = set()
    pool = rng.permutation(n)
    cursor = 0
    notes: list[tuple[str, np.ndarray, str]] = []  # fault type, rows, detail

    def take(k: int) -> np.ndarray:
        nonlocal cursor
        picked: list[int] = []
        while len(picked) < k and cursor < len(pool):
            row = int(pool[cursor])
            cursor += 1
            if not used_rows[row] and claim[row] not in used_claims:
                picked.append(row)
        rows = np.array(picked, dtype=np.int64)
        used_rows[rows] = True
        return rows

    def take_where(k: int, allowed: np.ndarray) -> np.ndarray:
        candidates = np.flatnonzero(allowed & ~used_rows)
        candidates = candidates[[claim[r] not in used_claims for r in candidates]]
        rows = (
            rng.choice(candidates, min(k, len(candidates)), replace=False)
            if len(candidates)
            else np.empty(0, dtype=np.int64)
        )
        for r in rows:
            used_claims.add(claim[r])
        used_rows[rows] = True
        return np.sort(rows)

    # paid_to_date decreasing without a recovery
    rows = take_where(
        _count(spec.paid_to_date_decreasing_without_recovery, size),
        has_previous & (paid[np.maximum(previous, 0)] > 0) & ~recovered & (status != "CLOSED_NIL"),
    )
    for r in rows:
        paid[r] = np.round(paid[previous[r]] * rng.uniform(0.5, 0.9), 2)
        ceded_paid[r] = min(ceded_paid[r], paid[r])
    notes.append(
        (
            "paid_to_date_decreasing_without_recovery",
            rows,
            "paid_to_date lower than the previous valuation",
        )
    )

    # one payment 20 to 50 times the line's median payment, carried by every later valuation
    line_of_claim = world.c_line[np.array([int(c) - 1 for c in claim])]
    medians: dict[str, float] = {}
    for line in scenario.lines:
        positive = increase[(line_of_claim == line) & (increase > 0)]
        medians[line] = float(np.median(positive)) if len(positive) else 0.0
    rows = take_where(
        _count(spec.extreme_payment_outliers, size), (increase > 0) & (status != "CLOSED_NIL")
    )
    for r in rows:
        spike = round(float(rng.uniform(20, 50)) * medians[str(line_of_claim[r])], 2)
        later = (claim == claim[r]) & (vdate >= vdate[r])
        paid[later] = np.round(paid[later] + spike, 2)
        notes.append(
            (
                "extreme_payment_outliers",
                np.array([r]),
                f"payment of {spike} added to paid_to_date from this row",
            )
        )

    # empty currency and unknown status labels, on rows of claims not faulted otherwise
    rows = take(_count(spec.missing_currency, size))
    currency[rows] = None
    notes.append(("missing_currency", rows, "currency empty"))
    rows = take(_count(spec.unknown_status_labels, size))
    labels = rng.choice(np.array(UNKNOWN_STATUS_LABELS, dtype=object), len(rows))
    status[rows] = labels
    notes.append(("unknown_status_labels", rows, "status label outside the dictionaries"))

    valuations = valuations.with_columns(
        pl.Series("paid_to_date", paid),
        pl.Series("ceded_paid_to_date", ceded_paid),
        pl.Series("status", status.tolist()),
        pl.Series("currency", currency.tolist()),
    )

    # exact duplicate rows (the dictionary-driven mess adds more of them)
    n_dup = _count(spec.duplicate_valuation_rows, size) + int(
        round(scenario.messiness.exact_duplicate_share * n)
    )
    free = np.flatnonzero(~used_rows)
    duplicated = (
        np.sort(rng.choice(free, min(n_dup, len(free)), replace=False))
        if len(free)
        else np.empty(0, dtype=np.int64)
    )
    valuations, new_row = _insert_duplicates(valuations, duplicated)
    stamp = vdate.astype(str)
    for fault_type, rows, detail in notes:
        faults += [
            Fault(fault_type, "claim_valuations", f"{claim[r]}|{stamp[r]}", int(new_row[r]), detail)
            for r in rows
        ]
    faults += [
        Fault(
            "duplicate_valuation_rows",
            "claim_valuations",
            f"{claim[r]}|{stamp[r]}",
            int(new_row[r]) + 1,
            "exact copy of the row above",
        )
        for r in duplicated
    ]
    out["claim_valuations"] = valuations

    # --- premiums: extra exact duplicates from the mess settings ----------------------------
    premiums = frames["premiums"]
    n_dup = int(round(scenario.messiness.exact_duplicate_share * premiums.height))
    if n_dup:
        picked = np.sort(rng.choice(premiums.height, n_dup, replace=False))
        premiums, new_row = _insert_duplicates(premiums, picked)
        keys = frames["premiums"]["transaction_id"].to_list()
        faults += [
            Fault(
                "duplicate_premium_rows",
                "premiums",
                keys[r],
                int(new_row[r]) + 1,
                "exact copy of the row above",
            )
            for r in picked
        ]
        out["premiums"] = premiums
    return out, faults
