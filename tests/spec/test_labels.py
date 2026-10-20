"""Label normalisation, blueprint section 6.3 layer 1."""

import pytest

from actuarycanary.spec.labels import normalise_label


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("STATUSON", "statuson"),
        ("Statü Son", "statuson"),
        ("statu_son", "statuson"),
        ("ÖDEME TARİHİ", "odemetarihi"),
        ("ODEMETARIHI", "odemetarihi"),
        ("ödeme tarihi", "odemetarihi"),
        ("Payment Date", "paymentdate"),
        ("İHBAR", "ihbar"),
        ("ıhbar", "ihbar"),
        ("O/S", "os"),
        ("  Şirket   Kodu ", "sirketkodu"),
        ("Çğüöşı", "cguosi"),
    ],
)
def test_normalise_label(label: str, token: str) -> None:
    assert normalise_label(label) == token
