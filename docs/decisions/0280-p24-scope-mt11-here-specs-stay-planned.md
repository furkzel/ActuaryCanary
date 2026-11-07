# 0280 — P24 builds MT11; the tier B specs stay `implemented: false` until the integration

## Context
The handover listed MT11 (bootstrap) under P26 (uncertainty and discounting), while the item P24 names the over-dispersed Poisson bootstrap as its first work item. Building a spec also means setting `implemented: true`; the run catalogue then holds the spec, its ID and version enter the run id (`manifest.run.run_id`), and every run id, the golden copy, the examples and the guide move. P24 may not touch the pipeline, the report, the examples or the goldens; the wiring is the integration item P25b.

## Decision
- P24 builds MT11 as a method: simulated reserves per origin and in total, summaries, cash flows by calendar period, residuals and the scale parameter. P26 keeps RS05, M12, the discounting of the simulated cash flows (CV10, RS04) and the one-year view; it no longer builds MT11 itself.
- The specs of P24 (MT11–MT16, MT22, AE02) keep `implemented: false`. The implementation of each is recorded in `methods.registry` (function, spec version, inputs), and a test checks that every spec of P24 has a registry entry whose version equals the spec's. The integration sets `implemented: true`, extends the version-1 scope test and regenerates the goldens in one step.

## Consequences
- No run id, golden file or example changes in P24.
- The handover lists for the integration which functions to call and what to record.
