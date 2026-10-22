"""quality.json and the terminal summary of a quality report."""

import json
from dataclasses import asdict
from datetime import date
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from actuarycanary.quality.model import QualityReport, Score
from actuarycanary.report import numbers

QUALITY_NAME = "quality.json"
QUALITY_VERSION = 1
_STYLE = {"BLOCKING": "bold red", "WARNING": "yellow", "INFO": "dim"}
_MODULE_STYLE = {"ok": "green", "limited": "yellow", "unable": "bold red"}


def show_score(score: Score) -> str:
    return numbers.EMPTY if score.value is None else str(numbers.round_half_away(score.value, 1))


def _plain(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def quality_json(report: QualityReport) -> str:
    """The report as JSON: unrounded scores, no clock time, so a rerun writes the same file."""
    body = asdict(report)
    body["quality_version"] = QUALITY_VERSION
    body["scores"] = {
        "overall": body.pop("overall"),
        "by_concept": body.pop("by_concept"),
        "by_field": body.pop("by_field"),
        "by_dimension": body.pop("by_dimension"),
    }
    return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False, default=_plain) + "\n"


def print_summary(console: Console, report: QualityReport) -> None:
    """Score, findings by severity, what cannot run, and what was loaded."""
    counts = ", ".join(f"{report.count(s)} {s.lower()}" for s in ("BLOCKING", "WARNING", "INFO"))
    console.print(
        f"[bold]Data quality {show_score(report.overall)}[/bold] / 100 "
        f"({report.overall.rules} rules evaluated; {counts})"
    )
    coverage = Table(title="Coverage", title_justify="left")
    for column in ("Concept", "Rows", "First", "Last", "Quality score"):
        coverage.add_column(column, justify="left" if column == "Concept" else "right")
    for c in report.coverage:
        score = report.by_concept.get(c.concept)
        coverage.add_row(
            c.concept if c.loaded else f"{c.concept} (not found)",
            numbers.count(c.rows) if c.loaded else numbers.EMPTY,
            str(c.first or numbers.EMPTY),
            str(c.last or numbers.EMPTY),
            show_score(score) if score else numbers.EMPTY,
        )
    console.print(coverage)
    if report.findings:
        table = Table(title="Findings", title_justify="left")
        for column in ("Severity", "Rule", "Count", "What", "Examples", "Modules"):
            table.add_column(
                column, overflow="fold", justify="right" if column == "Count" else "left"
            )
        for f in report.findings:
            where = ", ".join(f"{r.file} [{r.sheet}] row {r.row}" for r in f.refs[:2])
            table.add_row(
                f"[{_STYLE[f.severity]}]{f.severity}[/]",
                f.rule,
                f"{f.count}/{f.checked}",
                escape(f.message),
                escape(where + (" ..." if len(f.refs) > 2 else "")),
                " ".join(f.modules),
            )
        console.print(table)
    for m in report.modules:
        if m.status != "ok":
            console.print(
                f"[{_MODULE_STYLE[m.status]}]{m.module} {m.title}: {m.status}[/] "
                + escape("; ".join(m.reasons))
            )
