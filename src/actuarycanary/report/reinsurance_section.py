"""The M08 page (reinsurance) and the facts of its finding rules (RP01 1.5.0, record 0408):
the headline, the treaty table with the clause in use, gross, ceded and net loss ratios by
origin with RI04, the what-if side by side with RI05, the allocation notes and the
reconciliation with the reported ceded amounts."""

from typing import Any

import polars as pl

from actuarycanary.convert.allocation import APPROXIMATION, NOT_ALLOCATED
from actuarycanary.modules.reinsurance import ReinsuranceRun
from actuarycanary.modules.runner import AnalysisResult
from actuarycanary.report import numbers, scope
from actuarycanary.report.facts import FactSet, _put, find_result
from actuarycanary.report.language import t

RECONCILIATION_ROWS = 10  # treaty years listed on the page; all are in the output file
LAST_YEARS = 3
FOOTNOTE = (
    "{currency}; ceded share by treaty {ri03}, result ratio {ri04} on the incurred view (no ceded "
    "ultimate is selected), volatility {ri05}; the programme applied by {mt21}, allocation by "
    "{cv09}. Files: ceded_by_treaty.csv, ceded_allocation.csv, reinsurance_reconciliation.csv, "
    "ceded_by_size_band.csv, programme_comparison.csv."
)  # the reinsurance result of the last calendar years in the headline
TYPE_LABELS = {
    "QUOTA_SHARE": "Quota share",
    "SURPLUS": "Surplus",
    "EXCESS_OF_LOSS": "Excess of loss",
    "STOP_LOSS": "Stop loss",
    "FACULTATIVE": "Facultative",
}
CLAUSE_LABELS = {
    "payment_by_payment": "payment by payment",
    "occurrence_date": "fixed at the occurrence date",
    "line at the policy start": "line at the policy start",
    "none: index series missing": "none: index series missing",
}


def _by_segment(result, side: str) -> dict[str, float | None]:
    """The value of one side (premium or claims) of an RI01 view cut by segment."""
    if result is None or result.frame is None or "side" not in result.frame.columns:
        return {}
    rows = result.frame.filter(pl.col("side") == side)
    return {str(r["segment"]): r["value"] for r in rows.iter_rows(named=True)}


def _shares(analysis: AnalysisResult) -> list[dict[str, Any]]:
    """The ceded share of written premium and of claims incurred, per segment (RI01)."""
    cession = find_result(analysis, "RI01", ("segment",))
    premium, claims = _by_segment(cession, "premium"), _by_segment(cession, "claims")
    return [
        {
            "segment": name,
            "premium_share": numbers.ratio(premium.get(name)),
            "claims_share": numbers.ratio(claims.get(name)),
        }
        for name in sorted(set(premium) | set(claims))
    ]


def _terms(row: dict[str, Any]) -> str:
    kind = row["treaty_type"]
    if kind == "QUOTA_SHARE":
        return t("{share} ceded", share=numbers.ratio(row.get("cession_share")))
    if kind in ("EXCESS_OF_LOSS", "STOP_LOSS"):
        limit = row.get("limit")
        cover = numbers.amount(limit) if limit is not None else t("unlimited")
        if kind == "STOP_LOSS":
            return t(
                "{limit} xs {retention} of the loss ratio",
                limit=numbers.ratio(limit),
                retention=numbers.ratio(row.get("retention")),
            )
        return t(
            "{limit} xs {retention}", limit=cover, retention=numbers.amount(row.get("retention"))
        )
    if kind == "SURPLUS":
        return t("retained line {retention}", retention=numbers.amount(row.get("retention")))
    return ""


def _treaty_rows(
    run: ReinsuranceRun, shares: dict[tuple[str, int, str], float | None]
) -> list[dict[str, Any]]:
    table = run.treaty_table()
    differing = set()
    reconciliation = run.reconciliation()
    if reconciliation.height:
        differing = {
            (r["treaty_id"], r["treaty_year"])
            for r in reconciliation.filter(
                (pl.col("level") == "treaty year") & pl.col("differs")
            ).iter_rows(named=True)
        }
    rows = []
    for r in table.iter_rows(named=True):
        key = (r["treaty_id"], r["treaty_year"])
        clause = r.get("index_clause") or ""
        rows.append(
            {
                "treaty": r["treaty_id"],
                "year": r["treaty_year"],
                "type": t(TYPE_LABELS.get(r["treaty_type"], str(r["treaty_type"]))),
                "terms": _terms(r),
                "clause": t(CLAUSE_LABELS[clause]) if clause in CLAUSE_LABELS else "–",
                "claims_share": numbers.ratio(shares.get((*key, "claims"))),
                "premium_share": numbers.ratio(shares.get((*key, "premium"))),
                "computed": numbers.amount(r.get("computed_ceded_incurred")),
                "reported": numbers.amount(r.get("reported_ceded_incurred")),
                "hit": numbers.count(r.get("units_hit")),
                "exhausted": numbers.count(r.get("units_exhausted")),
                "reinstatements": numbers.factor(r.get("reinstatements_used")),
                "differs": key in differing,
            }
        )
    return rows


def _origins(analysis: AnalysisResult) -> list[dict[str, Any]]:
    """Per segment and origin: gross, ceded and net incurred over the gross earned premium of
    the segment, with RI04 of the segment."""
    cession = find_result(analysis, "RI01", ("segment", "origin_period"))
    result = find_result(analysis, "RI04", ("segment", "origin_period"))
    if cession is None or cession.frame is None or result is None or result.frame is None:
        return []
    claims = cession.frame.filter(pl.col("side") == "claims").select(
        "segment",
        "origin_period",
        pl.col("numerator").alias("ceded"),
        pl.col("denominator").alias("gross"),
    )
    joined = result.frame.select(
        "segment",
        "origin_period",
        pl.col("value").alias("ri04"),
        pl.col("denominator").alias("earned"),
    ).join(claims, on=["segment", "origin_period"], how="left")
    rows = []
    for r in joined.sort("segment", "origin_period").iter_rows(named=True):
        earned = r["earned"]

        def lr(x: float | None, e: float | None = earned) -> str:
            return numbers.ratio(x / e) if x is not None and e else "–"

        net = None if r["gross"] is None or r["ceded"] is None else r["gross"] - r["ceded"]
        rows.append(
            {
                "segment": r["segment"],
                "origin": r["origin_period"],
                "gross": lr(r["gross"]),
                "ceded": lr(r["ceded"]),
                "net": lr(net),
                "ri04": numbers.ratio(r["ri04"]),
            }
        )
    return rows


def _years(analysis: AnalysisResult) -> list[dict[str, Any]]:
    """The reinsurance result (RI02) of the last calendar years, per segment."""
    result = find_result(analysis, "RI02", ("segment", "calendar_period"))
    if result is None or result.frame is None or result.frame.height == 0:
        return []
    rows = []
    for name, part in result.frame.sort("segment", "calendar_period").group_by(
        "segment", maintain_order=True
    ):
        for r in part.tail(LAST_YEARS).iter_rows(named=True):
            rows.append(
                {
                    "segment": str(name[0]),
                    "period": str(r["calendar_period"]),
                    "result": numbers.amount(r["value"]),
                }
            )
    return rows


def _allocation_notes(run: ReinsuranceRun) -> list[dict[str, Any]]:
    table = run.allocation_table()
    if table.height == 0:
        return []
    summary = (
        table.group_by("method")
        .agg(pl.col("parts").sum(), pl.col("amount").abs().sum())
        .sort("method")
    )
    return [
        {
            "method": t(r["method"]),
            "approximate": r["method"] in (APPROXIMATION, NOT_ALLOCATED),
            "parts": numbers.count(r["parts"]),
            "amount": numbers.amount(r["amount"]),
        }
        for r in summary.iter_rows(named=True)
    ]


def _scopes() -> dict[str, Any]:
    """The scope of every table of the page (record 0815). The treaties, the programmes and
    the allocation are booked per treaty and not by segment; the rest is cut by segment."""
    return {
        "shares": scope.declare("Ceded share by segment", scope.SEGMENT),
        "years": scope.declare("Reinsurance result by segment", scope.SEGMENT),
        "treaties": scope.declare("Treaties", scope.COMPANY),
        "origins": scope.declare("Loss ratios by segment and origin", scope.SEGMENT),
        "volatility": scope.declare("Volatility by line", scope.SEGMENT),
        "programmes": scope.declare("What-if programmes", scope.COMPANY),
        "allocation": scope.declare("Allocation notes", scope.COMPANY),
        "reconciliation": scope.declare(
            "Reconciliation with the reported ceded amounts", scope.COMPANY
        ),
    }


def reinsurance_page(
    analysis: AnalysisResult,
    run: ReinsuranceRun | None,
    comparison: pl.DataFrame | None,
    spec,
    currency: str,
) -> dict[str, Any]:
    if run is None:
        return {"available": False}
    ri03 = find_result(analysis, "RI03", ("treaty",))
    shares: dict[tuple[str, int, str], float | None] = {}
    if ri03 is not None and ri03.frame is not None:
        shares = {
            (r["treaty"], r["treaty_year"], r["side"]): r["value"]
            for r in ri03.frame.iter_rows(named=True)
        }
    ri05 = find_result(analysis, "RI05", ("segment", "line"))
    volatility = []
    if ri05 is not None and ri05.frame is not None:
        volatility = [
            {
                "line": f"{r['segment']} / {r['line']}",
                "gross": numbers.ratio(r["denominator"]),
                "net": numbers.ratio(r["numerator"]),
                "ratio": numbers.factor(r["value"]),
                "note": r["note"],
            }
            for r in ri05.frame.iter_rows(named=True)
        ]
    programmes = []
    if comparison is not None and comparison.height:
        programmes = [
            {
                "name": r["programme"],
                "treaties": numbers.count(r["treaties"]),
                "view": t(r["loss_view"]),
                "premium": numbers.amount(r["ceded_premium"]),
                "loss": numbers.amount(r["expected_ceded_loss"]),
                "commission": numbers.amount(r["commission"]),
                "reinstatement": numbers.amount(r["reinstatement_premium"]),
                "result": numbers.amount(r["net_result"]),
                "volatility": numbers.factor(r["volatility_ratio_mean"]),
            }
            for r in comparison.iter_rows(named=True)
        ]
    reconciliation = run.reconciliation()
    years_rows = (
        reconciliation.filter(pl.col("level") == "treaty year")
        if reconciliation.height
        else reconciliation
    )
    differing = years_rows.filter(pl.col("differs")) if years_rows.height else years_rows
    return {
        "available": True,
        "currency": currency,
        "shares": _shares(analysis),
        "years": _years(analysis),
        "clause": t(CLAUSE_LABELS[run.settings.index_clause]),
        "treaties": _treaty_rows(run, shares),
        "origins": _origins(analysis),
        "volatility": volatility,
        "scopes": _scopes(),
        "programmes": programmes,
        "allocation": _allocation_notes(run),
        "compared": years_rows.height,
        "differences": differing.height,
        "reconciliation": [
            {
                "treaty": r["treaty_id"],
                "year": r["treaty_year"],
                "computed": numbers.amount(r["computed_ceded_incurred"]),
                "reported": numbers.amount(r["reported_ceded_incurred"]),
                "difference": numbers.amount(r["difference"]),
            }
            for r in differing.head(RECONCILIATION_ROWS).iter_rows(named=True)
        ],
        "footnote": t(
            FOOTNOTE,
            currency=currency,
            ri03=spec("RI03"),
            ri04=spec("RI04"),
            ri05=spec("RI05"),
            mt21=spec("MT21"),
            cv09=spec("CV09"),
        ),
    }


def add_reinsurance_facts(facts: FactSet, run: ReinsuranceRun | None) -> None:
    """Facts of KF44 to KF46: treaty years whose computed and reported ceded amounts differ,
    layers exhausted or reinstatements used up, and the share of the booked ceded amounts that
    is unallocated or allocated as an approximation. A fact the run cannot compute is absent."""
    if run is None:
        return
    reconciliation = run.reconciliation()
    years = (
        reconciliation.filter(pl.col("level") == "treaty year")
        if reconciliation.height
        else reconciliation
    )
    if years.height:
        differing = years.filter(pl.col("differs"))
        _put(facts, "reinsurance_differences", float(differing.height), "count")
        _put(facts, "reinsurance_years_compared", float(years.height), "count")
        names = ", ".join(dict.fromkeys(differing["treaty_id"].to_list()))
        if names:
            _put(facts, "reinsurance_differing_treaties", names, "text")
    if run.application is not None:
        layers = run.application.layer_frame()
        used: list[str] = []
        for r in layers.iter_rows(named=True):
            section = next(
                s
                for s in run.inputs.sections
                if s.treaty_id == r["treaty_id"] and s.inception == r["inception_date"]
            )
            reinstated = (
                section.reinstatements is not None
                and r["reinstatements_used"] is not None
                and r["reinstatements_used"] >= section.reinstatements - 1e-12
            )
            if r["aggregate_exhausted"] or (r["units_exhausted"] or 0) > 0 or reinstated:
                used.append(f"{r['treaty_id']} {r['inception_date'].year}")
        if layers.height:
            _put(facts, "layers_exhausted", float(len(used)), "count")
            if used:
                _put(
                    facts,
                    "layers_exhausted_names",
                    ", ".join(used[:5]) + (", …" if len(used) > 5 else ""),
                    "text",
                )
    if run.allocation is not None and run.allocation.rows.height:
        rows = run.allocation.rows
        total = float(rows["amount"].abs().sum())
        rough = float(
            rows.filter(pl.col("method").is_in([APPROXIMATION, NOT_ALLOCATED]))["amount"]
            .abs()
            .sum()
        )
        if total > 0:
            _put(facts, "approximate_allocation_share", rough / total, "ratio")
