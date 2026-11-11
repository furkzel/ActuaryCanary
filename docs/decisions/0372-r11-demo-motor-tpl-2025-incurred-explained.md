# 0372 — R11: MOTOR_TPL accident year 2025 incurred at 136 % of earned premium in the demo

## Context
In the demo (valuation date 2025-12-31) MOTOR_TPL accident year 2025 showed incurred of 136 % of earned premium at 12 months. Regenerated here from `synthetic/scenarios/demo.yaml` at size demo (seed 20261023): incurred 214,988,471 against earned premium 158,120,000 = 135.97 %. The same number, so the regenerated demo is the demo run.

## Findings
- **Two claims make 69 % of it.** Incurred of the 95 claims of the year (13 nil): 81.6 M (one claim), 66.3 M (another), 67.1 M (the other 93). Without the two the ratio is 42.4 %, like the years 2016–2020 (30–50 %).
- **Claim 1 is a heavy-tail draw on a small portfolio.** Cost at base-date prices 6.68 M, case reserve 81.6 M, nothing paid. The tail (probability 1 %, Pareto from 500,000, alpha 1.8, no cap) gives 3 claims above 500,000 in the year; the chance that a year of 95 claims holds one of 6.68 M or more is 0.9 %. The demo has 0.012 of the baseline portfolio, so one such claim outweighs the premium of a year. Not an error of the draw: a property of an uncapped alpha 1.8 tail at this size.
- **Claim 2 is a generator artefact.** It closes with nil (`nil_close_probability` 0.15, drawn independently of size) and ends with zero paid, but until it closes its case reserve is built from its latent cost (`claims.py`, reserve estimate uses `merged["cost"]` for nil claims too): 66.3 M of reserve, 31 % of the year's incurred, for a claim with no loss. Ultimates are unaffected (payments of nil claims are zeroed).
- **The case-reserve bias rows from 2022 are not the cause.** The reserve of claim 1 (81.6 M) is 0.62 of its whole cost at cut-off prices (6.68 M × index 19.79 = 132 M), so it is not overstated; the bias only multiplies reserves by 1.28 against the −10 % before 2022, far from a factor 3.
- **170 % is not a truth number.** The regenerated truth for NON_LIFE 2025 is: incurred 116.9 %, ultimate 411.6 % (MOTOR_TPL 548 %), because the ultimate is nominal and its payments run up to ten years past the cut-off at a CPI that keeps rising 33 % a year (0371). The 170 % of the review is therefore an estimate of the report, not of the generator (UNVERIFIED which one; the committed demo report was not opened).

## Decision
No generator change here. The 136 % is explained: a rare tail draw plus the reserve held on a nil-closing claim. Open for the owner (listed in HANDOVER Next): whether a claim that closes at nil carries a reserve built from its latent cost (as now), a reserve capped at the line's tail threshold, or none. Any of the three moves case reserves and incurred in every scenario that has a nil claim above the cap, hence golden entries and run ids; it is a one-line change in `claims.py` when decided.

## Consequences
- Anything about how MOTOR_TPL is modelled stays unchanged until this is decided.
