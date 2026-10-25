# 0623 — The severity methods and the budget of the medium run: defaults kept, owner decides

## Context
The P25 handover asked the integration to decide the default `gof_bootstrap` of MT17 (200) and MT18 (500) against the budgets of the medium run in `tests/test_performance.py`: 45 s cold and 30 s warm, without the import. Both numbers are defaults written in reviewed specifications (MT17 1.0.0, MT18 1.0.0); the integration may not change a specification or a threshold. P25 measured about 12 s for both methods on baseline medium (2 s and 10 s).

## Measured (2026-10-25, this machine, not idle in the sense of P25: the unwired code of `s/P24-tier-b-reserving` needs 43.1 s cold and 27.6 s warm here, against 19–25 s cold in earlier records)
- Baseline medium, step "Fitting claim sizes and extreme values": 33.5 s cold and 34.7 s warm (the step does not read spreadsheets, so cold and warm are the same work). Per group: MOTOR_TPL 2.6 s (MT17) and 9.2 s (MT18), MOTOR_OD 1.9 s and 16.4 s, PROPERTY 1.1 s and 1.0 s, GROUP_TERM_LIFE 0.3 s and 1.2 s; the sizes frame 0.5 s. MT18's 500 refits at each of 12 candidate thresholds is almost all of it.
- The tier B methods of M04 add 2.4 s (3.1 s against 0.8 s for the step).
- `test_medium_runs_inside_its_budget_cold_and_warm`: cold 63.6 s (budget 45), warm 64.7 s (budget 30). The same test on the unwired code would pass cold (43.1 s) and warm (27.6 s) here, narrowly.

## Decision
- The defaults of the specifications are kept (`gof_bootstrap` 200 and 500, 1,000 for the back-test of MT22 as written in 0618); a smaller default is a change of a reviewed specification and of what the methods are said to do, which the integration does not do.
- The budgets of the test are not changed either.
- Result: the budget test fails on this machine. Scaling by the ratio of the unwired runs (about 2) gives about 33 s cold and 32 s warm on the machine of the earlier records: inside cold, over warm by a little; UNVERIFIED, since that machine was not used.
- The owner decides, with these options: (a) amend MT17 and MT18 (a lower default `gof_bootstrap`, for example 100 for MT18, and a version bump), (b) raise the two budgets, (c) run the two severity methods only when asked (a setting), (d) leave the test failing as a known cost.

## Consequences
- `just test-all` has this one failure until the owner decides. `just check` (fast suite) is not affected.
