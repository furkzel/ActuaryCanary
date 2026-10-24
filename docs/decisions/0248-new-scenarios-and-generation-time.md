# 0248 — Scenarios reinsurance_heavy and life_book; what generation costs

## Context
The reinsurance methods need layers that are hit, a surplus and high cessions; the life methods need a life book; the recognition work needs the new feeds in the mess of real files.

## Decision
- **`reinsurance_heavy`** starts from the baseline and replaces the treaties: quota shares of 40 per cent (motor own damage) and 30 per cent (property), a per-risk layer on own damage, three stacked layers on third-party liability (retentions 100,000, 300,000 and 1,000,000 at base-date prices, indexed), an event layer on property with a low retention, and a surplus treaty on property (retained line 800,000, nine lines). The gross world is the baseline's (test: claims, policies and the gross amounts of the valuations are equal); only what is ceded differs. At tiny, every layer is hit (10, 3 and 3 claims for the three third-party layers).
- **`life_book`** starts from the baseline and enables the life book of record 0246.
- **`messy_headers`** starts from `life_book`, so that the later feeds, life ones included, arrive with Turkish and English headers from AL03, translated labels from AL04, text dates, title rows and exact duplicates, as the first six do. The logs are in the `_phase2` files (record 0241). The data checker passes through them (test).
- **`just synth all <size>`** writes every scenario of `synthetic/scenarios/` at one size (`python -m actuarycanary.synthetic write all <size>`).

## Time of generation (this machine, one process, files written, 2026-10-24)
| scenario | tiny | medium | large |
| --- | --- | --- | --- |
| baseline | 2.0 s | 49.0 s | 388.3 s |
| reinsurance_heavy | 2.3 s | 68.1 s | not run |
| life_book | 2.3 s | 77.8 s | 473.8 s |
| messy_headers | 2.4 s | 87.4 s | not run |
| demo, high_inflation, large_loss, reserve_bias_change | 1.9–2.0 s | not run | not run |

Rows of the later feeds: tiny (baseline) 1,008 rates, 12 treaties, 380 treaty movements, 15 recoveries, 1,507 ledger; with the life book 840 contracts' rows, 101 events, 1,529 flows (all under 2,000). Medium (life_book): 211,320 in-force rows, 24,902 events, 451,045 flows. Large (life_book): 1,165,316 in-force rows in two workbooks, 138,127 events, 2,493,113 flows in three workbooks, 39,117 treaty movements, 10,373 recoveries; the folder is 502 MB (baseline large 283 MB).

## Consequences
- The time of the baseline cannot be compared with the figure before P22 (an earlier measurement of the large baseline gave 201 s to write, on another day and load); the machine was not idle (other processes ran during the large runs), so these are upper bounds. The later feeds add the ledger, the treaty movements and the truth to a world that is simulated once.
- UNVERIFIED: peak memory of the large runs, which was 7.4 GiB for the run of `canary` on large (record 0082) but was not measured for the generator.
