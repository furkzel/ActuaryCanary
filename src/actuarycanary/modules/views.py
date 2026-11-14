"""The default views of a run: the breakdowns each measure is computed at (decision 0051).

A view is a tuple of breakdowns. The module runner computes one result per view; a reader who
wants another cut asks the engine for it. Segment and line come first because every module
reports by segment and line (blueprint 10); a measure without claims or policies falls back
to its all-business view by its own edge case.
"""

from dataclasses import dataclass

from actuarycanary.structures.periods import Period

SEGMENT_LINE = ("segment", "line")

DEFAULT_VIEWS: dict[str, tuple[tuple[str, ...], ...]] = {
    "PR01": ((*SEGMENT_LINE, "calendar_period"), ("calendar_period",)),
    "PR02": ((*SEGMENT_LINE, "calendar_period"),),
    "PR03": (SEGMENT_LINE,),
    "PR04": (("calendar_period",),),
    "PR05": (("calendar_period",),),
    "PR06": ((*SEGMENT_LINE, "calendar_period"),),
    "CL01": ((*SEGMENT_LINE, "origin_period"),),
    "CL02": ((*SEGMENT_LINE, "origin_period"),),
    "CL03": ((*SEGMENT_LINE, "origin_period"),),
    "CL04": (SEGMENT_LINE, ("calendar_period",)),
    "CL05": ((*SEGMENT_LINE, "origin_period"),),
    "CL06": ((*SEGMENT_LINE, "origin_period", "claim_size_class"),),
    "CL07": ((*SEGMENT_LINE, "origin_period"),),
    "CL08": (SEGMENT_LINE,),
    "CL09": ((*SEGMENT_LINE, "calendar_period"),),
    "CL10": ((*SEGMENT_LINE, "origin_period", "development_period"),),
    "CL11": ((*SEGMENT_LINE, "origin_period"),),
    "CL12": ((*SEGMENT_LINE, "origin_period"),),
    "RC01": ((*SEGMENT_LINE, "origin_period"),),
    "RC02": ((*SEGMENT_LINE, "origin_period"),),
    "RC03": (("recovery_type",), (*SEGMENT_LINE, "recovery_type")),
    "RC04": ((*SEGMENT_LINE, "recovery_type", "origin_period", "development_period"),),
    "RI01": ((), ("calendar_period",), ("origin_period",)),
    "RI02": (("calendar_period",),),
    "RI03": (("treaty",),),
    "RI04": (("origin_period",),),
    "RI05": (SEGMENT_LINE,),
    "EX01": (("calendar_period",),),
    "EX02": (("calendar_period",),),
    "EX03": (("calendar_period",),),
    "RT01": ((*SEGMENT_LINE, "origin_period"),),
    "RT02": ((*SEGMENT_LINE, "origin_period"),),
    "AE01": ((*SEGMENT_LINE, "origin_period"),),
    "RS01": ((*SEGMENT_LINE, "development_period"),),
    "RS02": ((*SEGMENT_LINE, "origin_period"),),
    "RS03": ((*SEGMENT_LINE, "origin_period"),),
}


@dataclass(frozen=True)
class View:
    """One view of a measure in a module: its breakdowns and, when the module needs another grain
    than the run's (ratios by month), the period."""

    breakdowns: tuple[str, ...]
    period: Period | None = None  # None: the origin and calendar period of the run


_BY_PERIOD = View(("calendar_period",))
_BY_MONTH = View(("calendar_period",), Period.MONTH)
_BY_LINE_AND_MONTH = View((*SEGMENT_LINE, "calendar_period"), Period.MONTH)
_BY_LINE = View((*SEGMENT_LINE, "calendar_period"))
# Views a module asks for instead of the default ones. M09 goes deeper than M05 on the same
# measures (by line and month, unit costs by line); M05 keeps the default views (record 0387).
_LEDGER_MONTH = View(("entity", "account_class", "calendar_period"), Period.MONTH)
_SHARE_MONTH = View(("entity", "calendar_period"), Period.MONTH)
MODULE_VIEWS: dict[str, dict[str, tuple[View, ...]]] = {
    "M10": {"FN01": (_LEDGER_MONTH,), "FN02": (_SHARE_MONTH,)},
    "M09": {
        "EX01": (_BY_PERIOD, _BY_MONTH, _BY_LINE_AND_MONTH),
        "EX02": (_BY_PERIOD, _BY_MONTH, _BY_LINE_AND_MONTH),
        "EX03": (_BY_PERIOD, _BY_MONTH),
        "EX04": (_BY_PERIOD, _BY_LINE),
        "EX05": (_BY_PERIOD, _BY_LINE),
    },
}


def views_of(module: str, measure: str) -> tuple[View, ...]:
    """The views of a measure in a module: the module's own, else the default ones."""
    own = MODULE_VIEWS.get(module, {}).get(measure)
    if own is not None:
        return own
    return tuple(View(tuple(b)) for b in DEFAULT_VIEWS.get(measure, ((),)))
