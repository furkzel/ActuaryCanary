"""RI03 Ceded share by treaty: a 30 % quota share and an excess-of-loss layer on four claims.

Spec IDs proved: RI03.
"""

import pytest

from actuarycanary.convert.bases import ReinsuranceBasis
from tests.measures.helpers import measure
from tests.measures.reinsurance_book import book


def test_ri03_shares_of_a_quota_share_and_a_layer() -> None:
    result = measure(book(), "RI03", "treaty", reinsurance=ReinsuranceBasis.CEDED)
    assert result.frame is not None, result.reason
    got = {(r["treaty"], r["side"]): r for r in result.frame.iter_rows(named=True)}
    # claims: ceded incurred over gross incurred 950 at the cut-off
    assert got[("QS", "claims")]["value"] == pytest.approx(285 / 950, rel=1e-12)
    assert got[("XL", "claims")]["value"] == pytest.approx(160 / 950, rel=1e-12)
    # premium: ceded premium over gross written premium 1000
    assert got[("QS", "premium")]["value"] == pytest.approx(0.3, rel=1e-12)
    assert got[("XL", "premium")]["value"] == pytest.approx(0.035, rel=1e-12)
    assert got[("QS", "claims")]["treaty_year"] == 2024
    assert got[("QS", "claims")]["note"] == ""
    assert result.frame["refs_reinsurance_treaties"].list.len().min() == 1


def test_ri03_a_quota_share_away_from_its_cession_is_noted() -> None:
    result = measure(book(qs_paid_d=60.0), "RI03", "treaty", reinsurance=ReinsuranceBasis.CEDED)
    assert result.frame is not None
    qs = result.frame.filter((result.frame["treaty"] == "QS") & (result.frame["side"] == "claims"))
    assert qs["value"][0] == pytest.approx(225 / 950)
    assert "differs from the cession share" in qs["note"][0]


def test_ri03_by_line_is_not_built() -> None:
    result = measure(book(), "RI03", "line", reinsurance=ReinsuranceBasis.CEDED)
    assert not result.available and "per treaty and treaty year" in result.reason
