# 0207 — Tolerances of the phase 2 methods, from the phase 1 lessons

## Context
Phase 1 showed two traps (records 0062, 0063, 0075). A stochastic range tested on the synthetic baseline fails because the synthetic world breaks the model's assumptions (calendar inflation, tails beyond ten years, catastrophe shocks), not because the code is wrong. A projection tested per accident year fails on the process variance of young, long-tailed origins.

## Decision (proposed, draft)
- **Stochastic methods** (MT11, MT17, MT18, MT19, MT20, MT24, MT27) have a calibration test on data drawn from the method's own model, with a fixed seed, behind `ACTUARYCANARY_MONTE_CARLO=1`. The coverage band is 90 to 99 per cent for 95 per cent intervals, as in MT06.
- Coverage or error on the synthetic baseline is reported as **information without a tolerance**, with the reason in the spec.
- **Projections** (MT12, MT13, MT14, MT16) are judged on the total per line against the truth, not per origin year: 5 per cent, or 10 per cent for MOTOR_TPL (and PROPERTY where catastrophes dominate, MT16). Per-origin ratios are printed as information.
- **Benchmarks against the chainladder package** use the frozen-reference pattern of record 0007. Bootstrap benchmarks allow for Monte Carlo error: the mean within 2 per cent of the chain-ladder reserve and the standard deviation within 5 per cent of the reference.
- **Fixtures** are hand-computed to 1e-12 (1e-9 where an optimiser or a chain of products is involved).
- **Tier C** ground-truth metrics compare each challenger with its champion. A pass/fail tolerance is set only where the synthetic truth makes one meaningful, for example GLM relativities, AUC on the large_loss scenario, or clustering against products.

## Consequences
- The generator (P22) must write the truths these tests read: claim-level settlement dates after the cut-off, rating-factor relativities, ceded amounts per treaty, the life multiplier and the lapse table.
- No tolerance in these drafts has been run. Every figure is a proposal for the owner's review.
