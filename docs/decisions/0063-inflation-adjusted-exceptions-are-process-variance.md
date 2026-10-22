# 0063 — MT07: the MOTOR_TPL misses are process variance of young long-tailed origins

## Context
Record 0044 named three exceptions to MT07's 5 % per accident year: MOTOR_TPL 2023 (baseline −15 %, high_inflation −17 %) and high_inflation MOTOR_TPL 2016 (−5.1 %). It attributed them to superimposed inflation that the CPI misses and to payments after ten years. The causes were examined here; the code was not changed.

## Evidence (measured 2026-10-22 on the medium data the owner wrote that day; simulations in memory)
**On the written medium data (seed 0):**
- MOTOR_TPL 2023 is −15.0 % in both scenarios. High_inflation 2016 is −2.9 %, inside 5 %. For MOTOR_TPL the ratios of the two scenarios agree to four decimals, because restating with the CPI removes what distinguishes them for this line. The data behind record 0044 were not kept, so why its figures (−17 % and −5.1 %) differ is not known (UNVERIFIED).
- The origin is not thin. The chain ladder's development from 36 months to ultimate is 1.247, from 7 link ratios between 36 and 48 months (1.06 to 1.14). The realised development of origins 2016 to 2022 from 36 months to their true ultimate is 1.19 to 1.39 (mean 1.27). For 2023 it is 1.47: this origin develops further than any earlier one.
- Superimposed inflation is not the explanation. The older origins carry the same 5 % a year and lie within −3 % to +2 %.

**Over 61 simulations of each scenario (seeds base + 0 to base + 60, medium, clean valuations), the value-date ultimate ÷ the truth:**

| MOTOR_TPL age (months) | 36 | 48 | 60 | 72 | 84 | 96 | 108 | 120 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mean | 0.961 | 0.971 | 0.979 | 0.979 | 0.979 | 0.984 | 0.984 | 0.978 |
| standard deviation | 0.107 | 0.082 | 0.061 | 0.048 | 0.041 | 0.032 | 0.025 | 0.015 |
| share within 5 % | 0.39 | 0.59 | 0.69 | 0.75 | 0.75 | 0.85 | 0.92 | 0.92 |

- Seed 0's −15 % at 36 months is about one standard deviation below the mean. The other lines are within 5 % almost always: MOTOR_OD (SD at most 0.24 %) and GROUP_TERM_LIFE always, PROPERTY in 87 to 100 % of origins depending on age.
- Only 3 % of simulations have every checked accident year within 5 %. Widening the tolerance to max(5 %, 2 Mack standard errors) only reaches 20 %, because Mack's standard error falls towards zero at old ages while the truth still pays after ten years.
- The small bias of about −2 % at every TPL age (0.978 at 120 months) matches the 1.9 % of the 2016 ultimate paid after ten years, which a tail factor of 1.0 leaves out.
- Per line, summed over accident years with at least three years of development: MOTOR_TPL mean 0.974, SD 0.040, within 5 % in 79 % of simulations and within 10 % in 97 %. MOTOR_OD, PROPERTY and GROUP_TERM_LIFE are within 5 % in every simulation. Seed 0: TPL −3.5 %, PROPERTY −1.3 %, MOTOR_OD +0.04 %, GROUP_TERM_LIFE 0.0 %.

## Decision
- Not a bug, and not a property of the method. The per-accident-year 5 % tolerance is tighter than the process variance of a long-tailed line in its early years.
- The test's named exceptions are now baseline and high_inflation MOTOR_TPL 2023, which are still outside 5 % and stay a strict expected failure. High_inflation MOTOR_TPL 2016 is inside 5 % on the current data, so it is checked with the other accident years.
- **Proposed specification change for the owner.** MT07 is not edited here.
  - Ground truth per line on the sum over accident years with at least three years of development: within 5 %, and within 10 % for MOTOR_TPL. All lines pass in 97 % of 61 simulations, and seed 0 passes.
  - Per-accident-year ratios are reported as information.
  - Not recommended: 5 % per accident year from 72 months only. Every year passes in only 39 % of simulations.

## Consequences
- The value-date ultimates are unchanged. A tail factor for long-tailed lines, or a check of development after ten years, would address the −2 % bias (P09 follow-up, not this item).
