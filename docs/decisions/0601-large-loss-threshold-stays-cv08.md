# 0601 — Large-loss threshold: CV08 keeps the default, MT18 only reports its own

## Context
Blueprint 18.2 left the default large-loss threshold rule open. Record 0010 chose the 99th percentile per segment and line (CV08). Record 0210 proposed that CV08 might adopt the extreme-value threshold of MT18 and left CV08 at the percentile until the owner decided.

## Decision
Chosen by the owner on 2026-10-24:
- CV08's 99th percentile per segment and line is the default threshold for M06 and for every large-loss view (CL12 and the views built on it).
- It is overridable in `project.yaml`: `large_loss.percentile` replaces the percentile, and `large_loss.thresholds` gives a fixed amount per "SEGMENT/LINE" group at value-date prices in reporting currency. The values in force go to the run manifest. This replaces the assumptions register as the place of the override.
- The threshold that MT18 selects (ForwardStop) is used only inside the extreme-value fit and is reported next to the CV08 threshold, with the share of claims and of incurred above each. It never decides which claims are LARGE.

## Consequences
- CV08 1.1.0, MT18 0.2.0 and M06 1.1.0 say so; the proposal of 0210 is not adopted. Their versions are in the run id, so run ids move with this record; no figure of a report moves.
- The override in `project.yaml` is specified here and not built: the severity and extremes item builds it, with a test that a fixed threshold changes the LARGE class and the manifest.
- LARGE shares keep their meaning across versions. An extreme-value threshold stays available to read, not to classify.
