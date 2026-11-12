# 0775 — A1b: the demo before the change

## Context
R08, R09 and R04 are judged on the demo as it runs on `main` (`f433f05`, run id `da2f0f9d044dedb9`, `canary demo`, English, 12 s). This record is the measurement before any change; record 0780 sets the same quantities beside it.

## What the demo shows
- **Link ratios per development column.** Every triangle (four lines, paid and incurred, ten origins) has 9, 8, 7, 6, 5, 4, 3 link ratios in the columns 12-24 to 72-84, **2 in 96-108 and 1 in 108-120**, no exclusions. Thin columns: 8 triangles × (96-108 with two, 108-120 with one).
- **Selected factors of the thin columns.** MOTOR_TPL incurred 108-120 = 0.9300 (the factor of the review); MOTOR_TPL paid 108-120 = 1.0499; all other lines and measures 1.0000 to four decimals in both thin columns. MOTOR_TPL 96-108: incurred and paid above 1 (two ratios, not touched by the rule of record 0776). Tail factor: 1.000, who = default, in all eight scopes.
- **Selected unpaid** (RS02 with MT10, nominal): GROUP_TERM_LIFE 69,160,632.15 · MOTOR_OD 12,100,252.97 · MOTOR_TPL 482,641,366.90 · PROPERTY 5,281,422.62; **all lines 569,183,674.63**; selected IBNR 254,925,008.61. Chain ladder unpaid by measure, for orientation: MOTOR_TPL paid 300,452,853.09 · incurred 625,356,485.08; MT07 (paid, inflation adjusted) MOTOR_TPL 147,063,980.64.
- **Bootstrap (MT11), nominal, seed 1, 10,000 simulations:** all lines mean 568,741,696.8 · VaR 99.5 % 1,264,224,250 · TVaR 99 % 1,523,302,816; present value: mean 314,819,650.8 · VaR 544,072,955.8 · TVaR 569,357,280. Lines (nominal mean · VaR 99.5 % · TVaR 99 %): GROUP_TERM_LIFE 69,160,632 · 104,582,478 · 105,949,673; MOTOR_OD 12,100,253 · 17,242,718 · 17,498,933; MOTOR_TPL 482,199,389 · 1,180,935,261 · 1,437,236,693; PROPERTY 5,281,423 · 18,250,849 · 19,456,308. Mack lognormal all lines: 569,183,675 · 1,042,114,083 · 1,068,615,319.

## Consequences
- Only MOTOR_TPL has a thin factor that differs from 1.000; the rule of 0776 can move only that line (and, through the total, the all-lines figures). The review's "+39.8 m" for 108-120 = 1.000 is the incurred 0.9300 → 1.0000 on the 2016 origin.
- The scratch outputs are outside the repository; nothing but this record is committed from the measurement.
