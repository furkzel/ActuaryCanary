"""The data quality section of the report page (an HTML fragment the report includes)."""

from functools import cache

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from actuarycanary.quality.model import QualityReport, SourceRef
from actuarycanary.quality.output import show_score
from actuarycanary.report import language, numbers
from actuarycanary.report.language import t
from actuarycanary.report.modules_section import module_title
from actuarycanary.report.render import TEMPLATE_DIR
from actuarycanary.spec.catalogue import SpecCatalogue

SECTION_TEMPLATE = "quality.html.j2"


@cache
def _environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.globals.update(tr=language.t, trh=language.th)
    return environment


def _refs(refs: tuple[SourceRef, ...]) -> str:
    return "; ".join(f"{r.file} [{r.sheet}] row {r.row}" for r in refs)


def render_quality_section(
    report: QualityReport, dq01_version: str, catalogue: SpecCatalogue | None = None
) -> str:
    scores = [
        {
            "level": t(level),
            "name": t(name) if level == "dimension" else name,
            "score": show_score(s),
            "rules": s.rules,
        }
        for level, group in (
            ("dimension", report.by_dimension),
            ("concept", report.by_concept),
            ("field", report.by_field),
        )
        for name, s in group.items()
    ]
    return (
        _environment()
        .get_template(SECTION_TEMPLATE)
        .render(
            overall=show_score(report.overall),
            rules=report.overall.rules,
            counts={s: report.count(s) for s in ("BLOCKING", "WARNING", "INFO")},
            spec=lambda spec_id: f"{spec_id} v{dq01_version}",
            coverage=[
                {
                    "concept": c.concept
                    if c.loaded
                    else t("{concept} (not found)", concept=c.concept),
                    "rows": numbers.count(c.rows) if c.loaded else numbers.EMPTY,
                    "first": c.first or numbers.EMPTY,
                    "last": c.last or numbers.EMPTY,
                    "score": show_score(report.by_concept[c.concept])
                    if c.concept in report.by_concept
                    else numbers.EMPTY,
                    "sources": ", ".join(c.sources),
                }
                for c in report.coverage
            ],
            modules=[
                {
                    "module": m.module,
                    "title": module_title(catalogue, m.module, m.title),
                    "status": t(m.status),
                    "status_code": m.status,
                    "reasons": "; ".join(t(x) for x in m.reasons)
                    + (
                        " " + t("Unavailable: {list}.", list=", ".join(m.unavailable))
                        if m.unavailable
                        else ""
                    ),
                }
                for m in report.modules
            ],
            findings=[
                {
                    "severity": t(f.severity),
                    "severity_code": f.severity,
                    "dimension": t(f.dimension),
                    "rule": f.rule,
                    "count": numbers.count(f.count),
                    "checked": numbers.count(f.checked),
                    "message": f.message,
                    "fields": ", ".join(f.fields),
                    "modules": ", ".join(f.modules),
                    "refs": _refs(f.refs),
                }
                for f in report.findings
            ],
            scores=scores,
            not_evaluated=[(rule, t(why)) for rule, why in report.not_evaluated],
        )
    )
