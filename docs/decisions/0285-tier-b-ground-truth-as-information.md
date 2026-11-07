# 0285 — Ground truth of the tier B reserving methods: how it is built and read

## Context
The item asks for ground truth on `baseline medium` and `high_inflation medium` on the total per line, with the deviations on the synthetic baseline reported as information. The specs give tolerances on named scenarios (MT12 baseline and reserve_bias_change, MT13 and MT16 baseline, MT14 baseline MOTOR_TPL, MT15 high_inflation). The local copies of high_inflation and reserve_bias_change are older than P22 (HANDOVER); their reserving feeds are complete, but their `ultimates.csv` has no earned premium at the cut-off rate.

## Decision
- One slow module, `tests/methods/test_tier_b_ground_truth.py`, builds the triangles as a run would (annual accident years and development, gross, TRY at the cut-off rate; value-date prices with CPI_TR for MT16) after undoing the injected amount faults, and compares with `truth/ultimates.csv`. Every result is printed with the tolerance of the spec and the lines outside it. The tests fail only when a line is missing or a ratio is not a positive number: the deviations are information, as the item says, and are recorded in the handover.
- Inputs the platform does not build yet are taken as the test sees fit and said in the test: non-nil counts are the reported counts of the claims whose latest status is not CLOSED_NIL (CL04 at the cut-off); catastrophe claims are the claims with an event code; earned premium comes from the truth (for the older copies, earned premium times the ratio of the TRY ultimate to the gross ultimate); exposure from `truth/frequency_severity.csv`.
- MT14's true tail is the one the spec names: ultimate over paid at the last age of the oldest accident year by `truth/development_pattern.csv` (MOTOR_TPL 2016: 1.0192). `ultimates.csv` gives another picture for the same year (paid at the cut-off 72 per cent of the ultimate); the difference is not resolved here.
- MT15's comparison for GROUP_TERM_LIFE is not meaningful: its claims index in the truth is 1 (severity is a fixed share of the sum insured), while the paid amounts still grow with the sums insured.

## Consequences
- The results of 2026-10-25 are in the handover. MOTOR_TPL lies outside the tolerances of MT12, MT13 and MT14 on every scenario: the line's incurred development is not stable (incurred chain ladder 1.06 to 1.56 times the truth on accident years 2017 to 2025) and much of its cost is paid after ten years. These are findings about the synthetic line and the methods' assumptions, not defects of the implementations, which match their references.
