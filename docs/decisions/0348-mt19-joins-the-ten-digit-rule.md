# 0348 — MT19 joins the ten-digit rule

## Context
Record 0626 writes the floats of the new methods to 10 significant digits. The nine `survival_*.csv`
files already pass through the shared writer, but the MT19 rows of `diagnostics.csv` (tier A file,
written unrounded) did not: the `NON_PROPORTIONAL_HAZARDS` p-value differed by 2.2e-14 between
Windows and Linux (found by H12, 0360).

## Decision
- `ROUNDED_METHODS` in `modules/reserving_output.py` gains MT19. CV06 becomes 1.1.1 and names MT19
  beside MT11 to MT18, MT22 and AE02 (a clarification of 0626, not reviewed by the owner yet).
- The test of the digits of every float of the new files also checks the survival files and the
  MT19 rows of `diagnostics.csv`.

## Consequences
- The MT19 rows of `diagnostics.csv` move in their last digits; run ids move through the CV06 version.
