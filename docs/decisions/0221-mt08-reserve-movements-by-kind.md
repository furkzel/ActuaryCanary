# 0221 — MT08 scores case-reserve movements by kind (MT08 1.2.0)

## Context
`reserve_change` flagged 40 to 45 % of the MOTOR_OD movements (record 0060 era, HANDOVER). Cause, measured on baseline medium: of 28 967 MOTOR_OD movements 9 000 are reserves released to nothing (median log change -10.4) and 201 reserves opened from nothing (+8.8), against 19 766 revisions of a running reserve (median 0.0, 14 093 of them exactly 0). One median and MAD for all of them put every opening and release far out, and where MAD is zero the mean-deviation fallback flagged a fifth of the running revisions as well.

## Decision
- A reserve that did not move is not a movement and is not scored.
- A movement is scored as one of three variables, each against its own median and MAD within segment and line: `reserve_opening` (previous reserve zero), `reserve_release` (new reserve zero), `reserve_change` (positive on both sides). The formula of `y` is unchanged. Default `variables` and `allowed` list the five variables; the payment variables are untouched.
- A scale per claim size was tried in thought and left out: with the kinds apart every line is far below the owner's 10 %, and a size split would cut the groups below `min_group_size` on the thin lines.

## Consequences
Measured 2026-10-23 on the same data, flagged share of the reserve movements per line, MT08 1.1.0 then 1.2.0:
- baseline tiny: MOTOR_OD 40.1 % → 1.0 %, MOTOR_TPL 6.3 % → 1.4 %, GROUP_TERM_LIFE 0 % → 0 %, PROPERTY not scored in either.
- baseline medium: MOTOR_OD 44.9 % → 1.6 %, MOTOR_TPL 5.7 % → 1.5 %, PROPERTY 11.6 % → 1.8 %.
- high_inflation medium: MOTOR_OD 45.1 % → 1.6 %, MOTOR_TPL 5.7 % → 1.5 %, PROPERTY 11.7 % → 1.6 %.
- baseline large: MOTOR_OD 42.4 % → 1.6 %, MOTOR_TPL 5.7 % → 1.6 %, PROPERTY 12.1 % → 1.6 %.
- Recall of the injected payments 8 of 8 on baseline and high_inflation medium and on large (2 of 2 on tiny), other flagged payment rows unchanged (353, 328, 2 073). The 5 % mixed-population warning no longer fires on any of them.
- The report's anomaly counts, the method note of MT08 and the golden copy change; the run id changes with the MT08 version.
