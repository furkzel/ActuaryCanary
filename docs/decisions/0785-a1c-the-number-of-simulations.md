# 0785 — A1c: the number of simulations (remedy c), and the target NOT MET

## Seed script, remedies (a) + (b) + (c) (2026-11-12, demo, seeds 1 to 20)
| Line | Statistic | 10,000 (0784) | 20,000 | 50,000 |
| --- | --- | --- | --- | --- |
| **All lines** | VaR 99.5 % | 4.96 % | 2.73 % | **2.14 %** |
| **All lines** | TVaR 99 % | 4.06 % | 2.97 % | **2.21 %** |
| GROUP_TERM_LIFE | VaR / TVaR | 2.98 % / 2.55 % | 2.32 % / 1.72 % | 1.43 % / 1.27 % |
| MOTOR_OD | VaR / TVaR | 2.49 % / 2.23 % | 2.01 % / 1.85 % | 1.57 % / 1.45 % |
| MOTOR_TPL | VaR / TVaR | 5.65 % / 4.56 % | 3.31 % / 3.29 % | 2.38 % / 2.54 % |
| PROPERTY | VaR / TVaR | 6.17 % / 7.05 % | 3.81 % / 3.99 % | 2.91 % / 2.43 % |

All lines at 50,000: VaR 99.5 % 1,074.5 to 1,097.7 m (mean over the seeds 1,085.1 m), TVaR 99 % 1,107.2 to 1,131.9 m (1,117.6 m); largest deviation from the mean 1.17 % and 1.28 %. Script time 3.4 min at 20,000 and 4.0 min at 50,000. Every run agreed to the digit with the scratch proxy of record 0782.

## Decision
- **Default 50,000** (`odp_bootstrap.N_SIMULATIONS` and the tier B parameter `n_simulations`; MT11 1.4.0). Decision 4 of the item holds: the demo (`canary demo`, scratch folder, once each) took 12.6 s at 10,000 and 14.2 s at 50,000 (limit 13 + 60 s); the peak resident memory of the run process was 910 MB and 864 MB (limit 1 GB; the peak did not rise with the size, so the bootstrap does not set it). The run folder grows from 14 MB to 21 MB (the parquet files of the simulations). It is the best remedy: it halves the noise of 10,000 and makes nothing else worse.
- **Target NOT MET**: 2.14 % and 2.21 % against 2 %. With the outliers gone (0784) the spread falls as 1/√n (10,000 → 50,000: 4.96 → 2.14 %, factor 0.43 against 1/√5 = 0.45), so about 60,000 to 65,000 simulations would be expected to meet it on the demo; decision 4 stops at 50,000. MOTOR_TPL (2.38 % / 2.54 %) and PROPERTY (2.91 % / 2.43 %) stay above 2 % per line: their reserve is a ratio of small noisy late cells (0782); they do not block.
- **Options for the owner (not built):** (1) a default of 100,000 (by the same scaling about 4 s more than 10,000 on the demo, UNVERIFIED; outside decision 4); (2) a quantile estimator less sensitive to single draws (for example a Harrell–Davis estimate of VaR and TVaR); (3) report VaR and TVaR with their Monte Carlo standard error instead of a spread target; (4) a target on the largest deviation from the mean (1.17 % and 1.28 % now) instead of the range of 20 seeds, which grows with the number of seeds.
- Tests whose premise was the default of 10,000 are rewritten to 50,000: `tests/methods/test_tier_b_registry.py`, `tests/test_pipeline.py` and the slow `tests/test_pipeline_m12.py` (written, not run). M12 1.3.0 states that the bootstrap behind RS05 is MT11 1.4.0.
