# 0018 — Baseline calibration of motor third-party liability

## Context
After record 0016 the baseline gave a ten-year realised ultimate gross loss ratio of 1.77 for MOTOR_TPL. Targets for the baseline, ten-year realised ultimate gross loss ratio per line: MOTOR_OD 0.70–0.85, MOTOR_TPL 0.95–1.10 (later years may rise above), PROPERTY 0.55–0.90, GROUP_TERM_LIFE 0.50–0.70. Measured on the large baseline from `truth/ultimates.csv` (ultimate gross ÷ earned premium, accident years 2016–2025).

## Decision
- MOTOR_TPL `premium.per_policy` 5,500 → 9,500 in `synthetic/scenarios/baseline.yaml`. Nothing else changed: no frequency, severity, delay, reserving, reinsurance or seed value. No other scenario overrides the premium, so all five inherit the new value; `high_inflation`, `large_loss` and `reserve_bias_change` therefore also have the higher TPL premium.
- The other three lines were already inside their ranges and were left alone.

## Ten-year ratio per line, large baseline
| Line | Target | Before | After |
| --- | --- | --- | --- |
| MOTOR_OD | 0.70–0.85 | 0.785 | 0.785 |
| MOTOR_TPL | 0.95–1.10 | 1.771 | 1.025 |
| PROPERTY | 0.55–0.90 | 0.870 | 0.870 |
| GROUP_TERM_LIFE | 0.50–0.70 | 0.564 | 0.564 |

## MOTOR_TPL by accident year, before and after
| Year | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Before | 0.773 | 1.013 | 0.992 | 1.436 | 1.841 | 1.775 | 2.384 | 2.120 | 1.753 | 1.735 |
| After | 0.447 | 0.587 | 0.574 | 0.831 | 1.066 | 1.027 | 1.380 | 1.227 | 1.015 | 1.005 |

Other lines by accident year (unchanged): MOTOR_OD 0.52 rising to 0.88 (2023) and 0.81 (2025); PROPERTY 0.43–0.78 except 2.17 in 2023 (earthquake); GROUP_TERM_LIFE 0.51–0.62.

## Consequences
- The early TPL years sit near 0.45–0.60 and the later years above 1.0: the premium follows prices but not superimposed inflation, so the ratio drifts up as intended for an unadjusted tariff. The ten-year figure is in range; the shape over the years is a consequence of the other parameters, which were not touched.
- Tiny fixtures, `examples/` and the medium and large outputs were regenerated; only the expense and premium feeds and `ultimates.csv` changed. No test held an expected value that depended on the premium.
