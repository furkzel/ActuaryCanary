# 0010 — Large-loss threshold

## Context
Severity (CL06), large-loss share (CL12) and anomalies (M06) separate large claims. The version 1.0 input has no size class, and the blueprint left the threshold rule open (section 18.2).

## Decision
Chosen by the owner on 2026-10-20 (CV08):
- A claim with an event code is CATASTROPHE.
- Default threshold: the 99th percentile of claim size per segment and line, where size is gross incurred at the cut-off at value-date prices (CV02), over the non-nil claims of all origins.
- Fewer than 100 non-nil claims in a line: the threshold of its segment; fewer in the segment: no LARGE class.
- The user may set a fixed threshold per segment and line in the assumptions register; it replaces the percentile and is written to the run manifest.
- The class is fixed for the whole run.

## Consequences
- About one per cent of claims are LARGE by construction in every line; a fixed amount per line is how a business definition is expressed.
- An extreme-value threshold (tier B) can replace the percentile later through a new record.
