# 0060 — MT08: why the injected payments were missed, and a third variable

## Context
MT08 1.0.0 recalled 0 of the 8 injected extreme payments on baseline medium (record 0043). Before changing anything, the cause was looked for.

Not a bug:
- Row identity: after canonical de-duplication no claim has two rows on one valuation date; all 8 injected rows are scored as paid flows, on the date of the fault.
- Units: the 8 claims are in TRY (rate 1); the scored amount is the row's own payment plus the spike.
- Basis: paid flows are differences of consecutive rows per claim (CV04), as specified.

A design mismatch:
- The generator adds 20 to 50 times the line's median monthly payment to one row (ln 3.0 to 3.9). Log payments of a segment and line have a robust standard deviation (MAD / 0.6745) of 1.02 (GROUP_TERM_LIFE), 1.57 (MOTOR_OD), 2.02 (MOTOR_TPL) and 2.65 (PROPERTY). Severities are lognormal with sigma 1.0 to 1.3 plus a Pareto tail, they are split into several payments, and ten years of nominal prices (CPI about 13 times higher at the end) are pooled.
- |z| above 3.5 therefore needs a payment about 245 times the median in MOTOR_OD and about 1,175 times in MOTOR_TPL. The spikes reached z 1.16 to 2.51. Within one payment year the spread is still 1.2 to 2.5; that grouping recalled 2 of 8. A lower threshold was not tried as a fix: the brief rules out tuning a threshold for a test.
- The spikes differ in another way: the case reserve did not move with them, so incurred jumped (for example from 7,484 to 534,227 TRY on one PROPERTY claim). When a payment is drawn from the case reserve, incurred stays where it was. This holds in the synthetic world, and in claims handling generally.

Measured on baseline medium, with the specified z, threshold 3.5 and groups (recall; other flags per 1,000 payments):

| Variable | Recall | Other flags |
| --- | --- | --- |
| ln payment (1.0.0) | 0/8 | 2.7 |
| ln payment, grouped also by payment year | 2/8 | 7.2 |
| payment over the previous incurred | 5/8 | 43.5 |
| payment over the previous case reserve | 6/8 | 73.4 |
| log change of incurred on every row where it moved | 7/8 | 88.9 (mostly nil closures) |
| log change of incurred on rows with a payment where it moved | 8/8 | 12.4 |

## Decision
Approved by the owner on 2026-10-22: MT08 1.1.0 adds the variable `incurred_change_at_payment`:
- ln((I+(v_n) + 1) / (I+(v_n-1) + 1)), with I = paid + case reserve, converted at each row's constant development rate (CV01) and clipped at zero;
- on consecutive rows that carry both paid and reserve, where the paid flow is positive and incurred moved;
- a value whose currency has no rate on either row is not scored and is counted, as for reserve changes;
- same robust z, threshold 3.5, minimum group 30 and groups (segment, line). `paid_flow` and `reserve_change` are unchanged.
- The ground truth counts a payment as recalled when its row is flagged on `paid_flow` or on the new variable. Other flags are flagged payment rows (either variable, each row once) that were not injected.

Measured on 2026-10-22 with MT08 1.1.0:

| Data | Recall | Other flagged payment rows per 1,000 payments |
| --- | --- | --- |
| baseline medium (tuned on) | 8/8 | 15.1 (2.7 before) |
| high_inflation medium (validation) | 8/8 | 14.1 (paid_flow alone: 0/8) |
| tiny fixture (validation) | 2/2 | 0 |

The highest flag rate of the new variable in a group is 4.0 % (MOTOR_TPL), below the 5 % warning.

## Consequences
- The ground-truth test passes on baseline and high_inflation and is no longer an expected failure. `anomalies.csv` gains rows with the new variable; its columns do not change.
- `reserve_change` is unchanged and still flags 45 % of MOTOR_OD reserve movements (the warning says so). Most months leave the reserve unchanged, so the MAD is zero and the fallback deviation is small. This is not part of this item.
- The docstring of `modules/anomalies.py` still says the recall is below the specification. That file lies outside `methods/` and was left unchanged.
