# 0062 — MT06: the coverage gap comes from the synthetic world, not from the code

## Context
Over 200 simulations of baseline, the true reserve fell below Mack's lognormal 95th percentile in 0.81 (GROUP_TERM_LIFE), 0.875 (MOTOR_OD), 0.65 (MOTOR_TPL) and 0.70 (PROPERTY) of runs. MT06 asks for 0.90 to 0.99 (record 0045). The question was whether this is a bug or a property of the data. The code was not changed.

## Evidence (measured 2026-10-22; scripts were run, not kept in the repository)
**The code is calibrated where Mack's assumptions hold.**
- The standard errors match the chainladder package on GenIns, RAA and clrd_wkcomp to 1e-6 (benchmark tests).
- Control: triangles drawn from Mack's own model, with gamma link ratios of mean f(j) C and variance sigma²(j) C and the parameters fitted to GenIns, give coverage 0.939 over 4,000 runs. The standardised error (true − Mack) / se has mean 0.05 and root mean square 1.06. With RAA's parameters the coverage is 0.908 over 3,990 runs (rms 1.46).
- The test compares like with like: in every run, the latest diagonal of the triangle equals the truth's paid at cut-off.

**The synthetic world breaks Mack's independence of origins.** Coverage over 200 runs at portfolio scale 0.02, switching parts of the baseline off:

| Line | baseline | no inflation (CPI 0, superimposed 0) | no Pareto tail | neither |
| --- | --- | --- | --- | --- |
| GROUP_TERM_LIFE | 0.81 | 0.93 | 0.81 | 0.93 |
| MOTOR_OD | 0.875 | 0.96 | 0.875 | 0.955 |
| MOTOR_TPL | 0.65 | 0.835 | 0.61 | 0.865 |
| PROPERTY | 0.70 | 0.84 | 0.68 | 0.845 |

Root mean square of the standardised error, baseline → no inflation: 2.33 → 1.20, 2.03 → 1.18, 4.96 → 1.70, 2.97 → 1.49 (1 is expected). Scale is not the cause. At scale 0.1 (100 runs) the baseline gives 0.81 / 0.90 / 0.57 / 0.68, and no inflation gives 0.92 / 0.95 / 0.82 / 0.87.

- **Inflation** is the main cause. Past CPI ran from 8 to 65 % a year, and the simulated future runs on at 33 %. Future payments carry the future CPI, which a nominal paid chain ladder can only reach through past calendar inflation folded into its factors. Calendar effects make origins dependent, against MT06's own assumption "origins are independent". For MOTOR_TPL the true reserve is a median 66 % of the ultimate in the baseline and 19 % without inflation.
- **MOTOR_TPL, without inflation:** the reserve of the oldest origins (84 to 120 months) is 1.8 to 3.0 times Mack's reserve, summed over 60 runs. The truth still pays 1.9 % of the 2016 ultimate after ten years, which a tail factor of 1.0 cannot see.
- **PROPERTY, without inflation:** the 2023 earthquake (an origin shock) dominates the reserve at 36 months. Without the catastrophe events, the true reserve of that age falls from 8.1 to 2.3 million (summed over 60 runs).
- The Pareto tails are not the cause: removing them changes no coverage by more than 0.04.

## Decision
- Not a bug: the code and the test are unchanged, and the coverage test stays a strict expected failure.
- **Proposed specification change for the owner.** MT06 is not edited here.
  1. Replace the ground truth "200 synthetic baseline runs, 0.90 to 0.99" with a calibration test on triangles drawn from Mack's model. Gamma link ratios with the GenIns parameters, at least 2,000 runs, coverage 0.90 to 0.99. Measured: 0.939. 8,000 runs (both controls) took 3 minutes with other jobs running, so it would stay behind ACTUARYCANARY_MONTE_CARLO like the present test.
  2. Keep the synthetic baseline coverage per line as information without a tolerance, with the reason: calendar-year inflation breaks the independence of origins.
  3. Optional: an inflation-free baseline, holding MOTOR_OD and GROUP_TERM_LIFE to 0.90 to 0.99. Measured 0.955 and 0.93 at scale 0.02, and 0.95 and 0.92 at scale 0.1.

## Consequences
- The report's Mack ranges stay labelled as a lognormal approximation. On inflation-driven or long-tailed lines they are too narrow, and record 0045 already names the tier B bootstrap as the comparison.
