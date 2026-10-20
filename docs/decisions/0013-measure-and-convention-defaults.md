# 0013 — Measure and convention defaults

## Context
Several measures and conventions need a default that the blueprint does not fix. Each one changes numbers, so each is recorded.

## Decision
- Frequency (CL05) and severity (CL06) both count reported claims that are not CLOSED_NIL at the cut-off, so frequency times severity equals incurred per exposure; a parameter brings nil claims back.
- Cancellation rate (PR04): returned premium over WRITTEN plus ENDORSEMENT of the same booking period.
- Earning intervals exclude their end date; earned exposure is days / 365.25 to the earlier of end date and cancellation date (CV04).
- Premium signs: per file and type, when most non-zero amounts carry the opposite of the canonical sign, the whole type is flipped and noted (CV05).
- Exchange rates: an earlier spot rate is used for up to 7 days, then the period average (CV01); no cross rates through a third currency.
- Rounding half away from zero on the shortest decimal representation, at presentation only (CV06).
- Data quality score weights: BLOCKING 3, WARNING 1, INFO 0 (DQ01).
- Actual versus expected (AE01) uses the selection made at the earlier valuation, recomputed on the data known then unless a stored selection is supplied.
- Anomaly flags: robust z threshold 3.5 on log amounts within segment and line (MT08); isolation forest with 200 trees, 256 samples per tree, 1 per cent flagged, seed 1 (MT09).

## Consequences
- These defaults are parameters in the specs; overrides are written to the run manifest.
