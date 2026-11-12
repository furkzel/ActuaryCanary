# 0788 — A1c: the findings that read the bootstrap, read and left

## Context
Stage 4 of A1c: every finding of `spec/report/findings.yaml` (RP01) that quotes a bootstrap quantity or the gap between the bootstrap and Mack must still be true after the refit (records 0783 to 0785).

## Reading
- **KF33** (width of the reserve range) reads the mean and the 95th percentile of the all-lines range of M12 (the bootstrap where it ran) and fires at an upper width of 25 % or more. Demo, nominal: before 923.02 / 608.52 − 1 = 51.7 %, after 849.82 / 607.61 − 1 = 39.9 %. It still fires, and its words (the range is an indicative approximation, the uncertainty page shows the steps from the selected unpaid to the mean of the range) stay true. Its threshold is a reading of the width, not of the method, so it stays.
- **KF34** (discount effect) reads the selected unpaid, not the simulation (its text says so): unchanged.
- **KF13** (triangles without a Mack range) reads MT06 only: unchanged.
- No finding quotes VaR, TVaR, the coefficient of variation of the bootstrap, the pseudo-triangle shares or a gap between the bootstrap and Mack.

## Decision
No finding text, condition or threshold changes; RP01 keeps its version.
