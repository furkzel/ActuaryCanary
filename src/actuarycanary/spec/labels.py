"""Label normalisation used to match column names and values against the alias dictionary.

Blueprint section 6.3, layer 1: lower case with Turkish-aware folding of I, İ, ı and i,
accents removed, and punctuation and spaces dropped, so that STATUSON, Statü Son and
statu_son all become the token ``statuson``.
"""

import unicodedata

_TURKISH_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def normalise_label(label: str) -> str:
    folded = label.translate(_TURKISH_FOLD)
    decomposed = unicodedata.normalize("NFKD", folded)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in without_accents.casefold() if c.isascii() and c.isalnum())
