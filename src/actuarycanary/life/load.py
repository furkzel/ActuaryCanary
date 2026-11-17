"""Loading the life feeds: the personal fields CV11 keeps out (record 0441).

A birth date is never read: AL01 lists it as personal data, so recognition drops the column and
lists it like a name or an identity number. Sex is a field of life_in_force but is dropped on load
and listed the same way unless the run setting `life.use_sex` is true; it is then used only in
aggregated cells.
"""

from dataclasses import replace

from actuarycanary.io.excel import RawTable
from actuarycanary.recognition.tables import TableRecognition

LIFE_IN_FORCE, LIFE_EVENTS, FUND_FLOWS = "life_in_force", "life_events", "fund_flows"
LIFE_FEEDS = (LIFE_IN_FORCE, LIFE_EVENTS, FUND_FLOWS)
SEX = "sex"


def drop_sex(
    raw: RawTable, rec: TableRecognition, use_sex: bool
) -> tuple[RawTable, tuple[str, ...]]:
    """The canonical table without its sex column unless `use_sex`, and the source headers
    dropped."""
    if use_sex or SEX not in raw.frame.columns:
        return raw, ()
    headers = tuple(m.source for m in rec.mappings if m.used and m.field == SEX)
    return replace(raw, frame=raw.frame.drop(SEX)), headers
