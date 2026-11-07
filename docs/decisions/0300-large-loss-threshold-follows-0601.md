# 0300 — Large-loss threshold: built as record 0601 decided it, not as the work item words it

## Context
The work item for the severity and extremes item asks for "a default large-loss threshold rule: the owner's recorded choice (extreme-value threshold, with the 99th percentile as fallback when exceedances are fewer than the spec's minimum)". The recorded choice is record 0601 (owner, 2026-10-24), and CV08 1.1.0, MT18 1.0.0 and M06 1.1.0 (all `reviewed`) say the opposite way round:
- CV08's 99th percentile per segment and line stays the one large-loss threshold of a run, for M06 and every large-loss view (CL12 and what stands on it); it is overridable in `project.yaml`.
- The threshold that MT18 selects (ForwardStop) is used only inside the extreme-value fit and is reported next to the CV08 threshold, with the share of claims and of incurred above each. It never decides which claims are LARGE.
- MT18 has no fallback to the percentile: a group without a candidate threshold that leaves `min_exceedances` excesses is "not run", with the number of claims as the reason.

Following the work item's wording would change which claims are LARGE, and with them CL12, M06, the run ids and the golden copy, against a reviewed specification and a recorded owner decision. The work item also says to stop and ask when a specification is ambiguous in a way that changes numbers; here the specification is not ambiguous, the work item text differs from it.

## Decision
Built as 0601 and the specifications say; the work item's wording is not followed where it differs. Nothing is changed in CV08, MT18 or M06.
- MT18 selects its threshold by ForwardStop per group and reports it beside the CV08 threshold (`threshold_comparison`: both thresholds, claims and incurred above each; an excess is strictly above u, a LARGE claim is at or above the CV08 threshold). A group with too few excesses is not run; the comparison row is still written, with the CV08 side filled and the extreme-value side empty.
- The `large_loss` section of `project.yaml` is read by `methods/severity/large_loss.py` (`parse_large_loss`): `percentile` (between 0 and 1) and `thresholds` ("SEGMENT/LINE" to an amount above zero); an unknown key, a malformed key or a non-numeric value is an error. The values in force come out as a record for the run manifest (`manifest_record`).
- The two fields it produces are the ones CV08 already reads (`large_loss_percentile`, `large_loss_thresholds` of the measure inputs). A test shows that a fixed threshold and a percentile change the LARGE class through `size_classes`.
- How M06 takes the threshold: it keeps taking the CV08 threshold of its run (the `threshold` column of `size_classes`). The MT18 threshold is shown in M06 beside it, from `ExtremeValues.threshold_comparison`.

## Consequences
- If the owner did want the extreme-value threshold to classify, 0601 has to be superseded first, and CV08, M06, CL12 and the goldens change with it; the work then starts from `threshold_comparison`, which already holds both thresholds.
- The reading of `project.yaml` and the entry in the run manifest are not wired here (the parser lives in the severity package, outside `manifest` and `pipeline`): the integration item P25b calls `parse_large_loss` where the project metadata is read, passes the two fields to the measure inputs and writes `manifest_record()` to the manifest. The project metadata model must accept the `large_loss` key.
- Measured on the baseline at medium (record 0303): the selected threshold sits well below the CV08 threshold (5 to 20 per cent of claims above it, against about 1 per cent), so a switch would multiply the LARGE share by 5 to 20.
