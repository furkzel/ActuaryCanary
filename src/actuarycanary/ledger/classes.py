"""Account classes of the ledger, the defaults of CV12 and the name tokens a first proposal
reads (record 0421).

The tokens stand in for the entries of AL04: a value entry of the alias files needs a field with
a closed list of classes in `spec/data`, and `account_name` is free text, so the words an account
name may carry live here, one table, and can be read and tested.
"""

from typing import Literal

from actuarycanary.spec.labels import normalise_label

AccountClass = Literal[
    "PREMIUM",
    "CLAIMS_PAID",
    "OUTSTANDING",
    "UPR",
    "COMMISSION",
    "EXPENSE",
    "RI",
    "INVESTMENT",
    "OTHER",
]
ACCOUNT_CLASSES: tuple[str, ...] = (
    "PREMIUM",
    "CLAIMS_PAID",
    "OUTSTANDING",
    "UPR",
    "COMMISSION",
    "EXPENSE",
    "RI",
    "INVESTMENT",
    "OTHER",
)
BalanceKind = Literal["PERIOD", "YEAR_TO_DATE"]
PERIOD: BalanceKind = "PERIOD"
YEAR_TO_DATE: BalanceKind = "YEAR_TO_DATE"

# the classes whose balance is a stock at the month end; the others are flows (CV12)
STOCK_CLASSES = frozenset({"OUTSTANDING", "UPR"})
# classes compared with a platform measure; INVESTMENT and OTHER are mapped, not reconciled
RECONCILED_CLASSES: tuple[str, ...] = (
    "PREMIUM",
    "CLAIMS_PAID",
    "OUTSTANDING",
    "UPR",
    "COMMISSION",
    "EXPENSE",
    "RI",
)

# CV12: credit-normal classes are turned to positive magnitudes with -1, debit-normal with +1
DEFAULT_SIGN: dict[str, int] = {
    "PREMIUM": -1,
    "OUTSTANDING": -1,
    "UPR": -1,
    "CLAIMS_PAID": 1,
    "COMMISSION": 1,
    "EXPENSE": 1,
}

# first match wins, so the more specific classes come first ("unearned premium" before "premium",
# "reinsurance commission" before "commission")
NAME_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("UPR", ("kazanılmamış prim", "kpk", "unearned premium", "upr")),
    ("OUTSTANDING", ("muallak", "outstanding", "claims reserve", "tazminat karşılığı")),
    ("RI", ("reasürans", "reasurans", "reinsurance", "ceded", "devredilen")),
    (
        "CLAIMS_PAID",
        ("ödenen hasar", "ödenen tazminat", "hasar ödeme", "claims paid", "paid claims"),
    ),
    ("COMMISSION", ("komisyon", "commission")),
    (
        "PREMIUM",
        ("yazılan prim", "prim gelir", "written premium", "premium income", "gross premium"),
    ),
    ("EXPENSE", ("faaliyet gider", "genel yönetim", "operating expense", "administrative expense")),
    ("INVESTMENT", ("yatırım", "investment")),
    (
        "OTHER",
        (
            "banka",
            "bank",
            "kasa",
            "cash",
            "geçmiş yıl",
            "earlier year",
            "retained earnings",
            "karşılıklardaki değişim",
            "change in provision",
        ),
    ),
)
SHORT_TOKEN = 3  # a token this short (KPK, UPR) must be the whole name, not part of a word
_FOLDED_TOKENS = tuple((c, tuple(normalise_label(t) for t in tokens)) for c, tokens in NAME_TOKENS)


def class_of_name(name: str | None) -> str | None:
    """The class an account name points to through `NAME_TOKENS`, or None."""
    if not name:
        return None
    folded = normalise_label(name)
    for account_class, tokens in _FOLDED_TOKENS:
        if any((folded == t) if len(t) <= SHORT_TOKEN else (t in folded) for t in tokens if t):
            return account_class
    return None
