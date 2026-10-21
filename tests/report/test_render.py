"""The report page: self-contained, labelled, footnoted, deterministic."""

from actuarycanary.manifest.run import InputRecord, SheetRecord, SpecRecord
from actuarycanary.modules.reserving import ChainLadderSettings, run_reserving
from actuarycanary.report.render import ReportContext, render_report
from actuarycanary.spec.loader import load_specs
from tests.structures.test_mt01_triangles import _build

SPECS = load_specs()
USED = ("claim_valuations", "CV01", "CV04", "CV06", "MT01", "MT02", "CL01", "CL03", "RS01", "RS02")


def _context() -> ReportContext:
    catalogue = {f.spec.id: f.spec for f in SPECS.files}
    return ReportContext(
        title="ActuaryCanary",
        disclaimer="Indicative analysis.",
        package_version="0.1.0",
        run_id="0123456789abcdef",
        reserving=run_reserving(_build(), ChainLadderSettings()),
        findings=(),
        inputs=(InputRecord("claim_valuations", "cv.xlsx", 1, "ab" * 32, (SheetRecord("s", 12),)),),
        specs=tuple(SpecRecord(s, catalogue[s].version, catalogue[s].title_en) for s in USED),
        settings={},
    )


def test_report_is_self_contained_labelled_and_footnoted() -> None:
    html = render_report(_context())
    assert html.count("Indicative — not an official reserve or price") == 2  # cover, one group
    assert "0123456789abcdef" in html
    for spec_id in ("MT01", "MT02", "RS01", "RS02", "CV06"):
        assert f"{spec_id} v1.0.0" in html
    assert "NON_LIFE · MOTOR_OD" in html
    assert "<script src=" not in html  # plotly is inlined
    assert "Plotly.react" in html
    assert '"heatmap-0-paid"' in html


def test_report_numbers_follow_cv06_and_the_page_is_deterministic() -> None:
    html = render_report(_context())
    assert "<td>370</td>" in html  # latest paid of origin 2023 in the fixture
    assert html == render_report(_context())
