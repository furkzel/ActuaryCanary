"""Personal-data columns, recognised by header (AL01 personal_data) or by value profile.

Such columns are dropped on load and listed by name only (CV07). An 11-digit identity-number
profile drops a column whatever its header says (CV07). Phone, e-mail, IBAN and person-name
profiles drop a column only when its header names no data field exactly, so that a field
such as ``policy_id`` is not lost to a look-alike pattern.
"""

from rapidfuzz import fuzz, process

from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.value_profile import ValueProfile

PERSONAL_SHARE = 0.9  # share of values that must fit a personal-data pattern
FUZZY_PERSONAL = 90.0  # similarity (0-100) of a header to a personal-data alias
MIN_FUZZY_LENGTH = 5
MIN_NAME_VALUES = 10
MIN_NAME_DISTINCT = 0.3


def personal_kind(
    token: str, profile: ValueProfile, named: bool, dictionary: Dictionary
) -> tuple[str, str] | None:
    """(kind, evidence) when the column holds personal data; `named` is true when the header
    is a data field's canonical name or exact alias."""
    if token in dictionary.personal:
        kind, label = dictionary.personal[token]
        return kind, f"header is personal data ({label})"
    if not named and len(token) >= MIN_FUZZY_LENGTH:
        best = process.extractOne(
            token, list(dictionary.personal), scorer=fuzz.ratio, score_cutoff=FUZZY_PERSONAL
        )
        if best is not None:
            kind, label = dictionary.personal[best[0]]
            return kind, f"header close to personal data {label!r} ({best[1]:.0f})"
    if profile.national_id_share >= PERSONAL_SHARE:
        return (
            "national_id",
            f"values: {profile.national_id_share:.0%} are 11-digit identity numbers",
        )
    if named:
        return None
    patterns = (
        ("phone", profile.phone_share, "phone numbers"),
        ("email", profile.email_share, "e-mail addresses"),
        ("bank_account", profile.iban_share, "IBANs"),
    )
    for kind, share, what in patterns:
        if share >= PERSONAL_SHARE:
            return kind, f"values: {share:.0%} are {what}"
    if (
        profile.person_name_share >= PERSONAL_SHARE
        and profile.non_null >= MIN_NAME_VALUES
        and profile.distinct_share >= MIN_NAME_DISTINCT
    ):
        return "name", f"values: {profile.person_name_share:.0%} look like person names"
    return None
