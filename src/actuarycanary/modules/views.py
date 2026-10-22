"""The default views of a run: the breakdowns each measure is computed at (decision 0051).

A view is a tuple of breakdowns. The module runner computes one result per view; a reader who
wants another cut asks the engine for it. Segment and line come first because every module
reports by segment and line (blueprint 10); a measure without claims or policies falls back
to its all-business view by its own edge case.
"""

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
    "RI01": ((), ("calendar_period",), ("origin_period",)),
    "RI02": (("calendar_period",),),
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
