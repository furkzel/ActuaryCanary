# 0045 — How the Mack coverage is tested (MT06)

## Context
MT06 asks that, over 200 synthetic baseline runs, the true reserve lie below the lognormal 95th percentile in 90 to 99 per cent of runs. 200 medium simulations take about 15 minutes.

## Decision
Chosen by the owner on 2026-10-22:
- 200 simulations of baseline with seeds base + 1 to base + 200 at portfolio scale 0.02 (about 0.5 s each, 1.5 minutes in all), run only when ACTUARYCANARY_MONTE_CARLO=1, so `just test-all` stays fast; a strict expected failure when outside the range.

Chosen in this work item:
- Per line: gross paid triangle of the clean (fault-free) valuations, every currency at the truth's constant cut-off rate; true reserve = (ultimate − paid at cut-off) × that rate; compared with the total 95th percentile of Mack.
- Measured 2026-10-22: coverage GROUP_TERM_LIFE 0.81, MOTOR_OD 0.875, MOTOR_TPL 0.65, PROPERTY 0.70; all below the range.

## Consequences
- The Mack range is too narrow on this synthetic portfolio (calendar effects such as inflation break Mack's independence assumption); the tier B bootstrap is the planned comparison.
