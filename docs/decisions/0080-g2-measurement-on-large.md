# 0080 — Gate G2: performance on `large` measured against blueprint 14.3

## Context
Blueprint 14.3: the largest scenario (ten years, about one million claim transactions) loads, maps and reports in under two minutes on an ordinary laptop; changing a basis or a segment in the report takes under five seconds. No performance test exists yet (blueprint 13.2). `data/synthetic/baseline/large` predated the P02c generator fix, so it was written again with `just synth baseline large` (201 s).

## Decision
No decision; measurement only, 2026-10-23, 16-core Windows 11 desktop, not checked to be idle. `canary run data/synthetic/baseline/large --yes`, 994,821 valuation rows, 100,276 claims, run id `67cea8b8c2f5eb1c` on both runs:

| Run | Wall clock | Read and recognise | Anomalies (MT08, MT09) | Measures and modules | Writing the tables | Other stages |
| --- | --- | --- | --- | --- | --- | --- |
| cold (new files, empty reader cache) | 104.0 s | 29.2 s | 20.1 s | 14.7 s | 25.2 s | 12.6 s (with 2.8 s import) |
| warm (reader cache hit) | 71.5 s | 0.8 s | 20.0 s | 14.1 s | 24.4 s | 12.8 s |
| warm, `--basis net` | 77.3 s | | | | | |

Stages come from the progress hook of `pipeline.run` (cold 101.9 s, warm 72.2 s in process); the wall clocks include `uv run`. `lineage.csv` is 135 MB and `anomalies.csv` 29 MB, which explains most of the time spent writing the tables.

## Consequences
- Load-to-report is within two minutes, but on four of the six feeds: `large` has no `policies` or `premiums` spreadsheets (0017) and the reader reads spreadsheets only, so M05, PR02 and MT03–MT05 did not run. With those two feeds (5.7 million rows) the budget is UNVERIFIED.
- Changing a basis is a new run (77 s warm); the report page has no basis or segment switch. The five-second part of the budget is not met as worded; the owner decides whether it still applies to phase 1.
- Not built: a performance test in the suite. Quality on `large` found every injected fault except one extreme payment outlier (DV-CLV-15 counts 7 of 8); cause UNVERIFIED.
