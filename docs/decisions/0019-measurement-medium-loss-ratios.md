# 0019 — Measurement: medium-size loss ratios of the five scenarios (gate G0)

## Context
Gate G0 asks how the five scenarios look at the medium size. This record only reports numbers; no parameter was changed. Method as in record 0018: ten-year (2016–2025) ultimate gross ÷ earned premium, summed over `truth/ultimates.csv` per line.

## Decision
No decision. Measured on 2026-10-21 with `just synth <scenario> medium`.

| Scenario | Generation | MOTOR_OD | MOTOR_TPL | PROPERTY | GROUP_TERM_LIFE |
| --- | --- | --- | --- | --- | --- |
| baseline | 49.8 s | 0.808 | 0.957 | 0.789 | 0.595 |
| messy_headers | 58.4 s | 0.808 | 0.957 | 0.789 | 0.595 |
| high_inflation | 49.6 s | 1.361 | 4.285 | 1.274 | 0.596 |
| large_loss | 60.7 s | 0.808 | 1.477 | 3.915 | 0.595 |
| reserve_bias_change | 60.2 s | 0.808 | 0.957 | 0.789 | 0.595 |

MOTOR_TPL by accident year (2016 … 2025):
- baseline, messy_headers, reserve_bias_change: 0.658, 0.496, 0.536, 0.562, 1.056, 1.007, 1.163, 1.080, 1.242, 0.793
- high_inflation: 1.572, 1.289, 1.517, 1.977, 4.276, 4.763, 4.934, 4.615, 6.657, 3.210
- large_loss: 1.238, 1.294, 1.125, 0.961, 2.960, 1.822, 2.267, 1.533, 1.651, 0.999

Baseline against the record 0018 targets: all four lines inside their ranges. MOTOR_TPL 0.957 is only just above the lower bound 0.95 (large: 1.025), so medium sampling noise can move it out.

Other scenarios:
- messy_headers and reserve_bias_change equal the baseline to three decimals. Consistent: the first changes layout only, the second changes case-reserve bias, which does not enter ultimates.
- high_inflation: motor and property rise, group life is unchanged. Consistent: premium does not follow superimposed inflation, and life has none. The size is large (TPL 4.3, already 1.57 in 2016); whether that severity is wanted is for the owner to judge.
- large_loss: only TPL and PROPERTY move (3.9 for property); OD and life are untouched. Consistent with a heavier tail in those lines; at medium a few claims can dominate the property figure.

## Consequences
- The pooled PROPERTY figure adds TRY, USD and EUR rows. In the truth file `earned_premium` appears to be in TRY while `ultimate_gross` is in the row currency (USD/EUR rows give 0.10–0.13). Foreign rows are about 1% of volume, so the pooled 0.789 differs little from the TRY-only 0.796 and the TRY-converted 0.801. UNVERIFIED which unit `earned_premium` uses; the owner should confirm before measures read this file.
