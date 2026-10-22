# 0061 — MT09: every claim of the group in every tree

## Context
MT09 1.0.0 gave an AUC of 0.63 on baseline medium for the 18 claims whose amounts the faults changed (10 with a lowered paid to date, 8 with a spike), against at least 0.7 (record 0043).

Checks first: all 18 claims are scored; a higher score means more anomalous; the groups are NON_LIFE (17,384 claims) and LIFE (855).

The features carry the signal on their own. As a single score, `negative_payments` has an AUC of 0.778: all 10 claims with a lowered paid have a negative flow, and no other NON_LIFE claim has one (10 of 17,384). Yet the forest ranked those 10 claims between 3,484th and 13,117th.

The cause is the sample size per tree. With `max_samples` 256, a tree sees 256 of 17,384 claims, so the chance that its sample holds one of the 10 claims is 1 − (1 − 10/17,384)^256 ≈ 14 %. In the other 86 % of trees the feature is constant and is never split on (scikit-learn skips constant features), so these claims are isolated only through their ordinary features. Rare extremes of the spikes are lost from small samples in the same way. The tiny fixture's groups (138 and 37 claims) are smaller than 256, so every tree there already sees every claim; its AUC is 0.90.

Measured AUC on baseline medium, seeds 1 / 2 / 3, features unchanged:

| max_samples | 256 | 512 | 1,024 | 2,048 | 4,096 | 8,192 | whole group |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (tuned on) | 0.630 / 0.616 / 0.609 | 0.708 / 0.703 / 0.664 | 0.799 / 0.748 / 0.767 | 0.864 / 0.852 / 0.849 | 0.893 / 0.892 / 0.895 | 0.894 / 0.901 / 0.905 | 0.901 / 0.907 / 0.907 |
| high_inflation (validation) | 0.633 / 0.580 / 0.586 | 0.668 / 0.674 / 0.672 | 0.772 / 0.762 / 0.742 | 0.834 / 0.821 / 0.827 | 0.876 / 0.872 / 0.870 | 0.878 / 0.887 / 0.881 | 0.890 / 0.899 / 0.893 |

Also measured, not adopted: adding the feature "largest log change of incurred at a payment" (the signal of record 0060) gives 0.979 (baseline) and 0.968 (high_inflation) with the whole group. The owner chose not to add it, because it repeats MT08's signal, which MT09 is meant to complement.

## Decision
Approved by the owner on 2026-10-22: MT09 1.1.0 sets the `max_samples` default to every claim of the group (`"all"`, without subsampling). An integer still caps the sample at that size and at the group size. Features, number of trees, contamination, seed and minimum group size are unchanged.

Measured on 2026-10-22, seed 1:

| Data | AUC amount faults, before → after | AUC all faulted claims, before → after |
| --- | --- | --- |
| baseline medium | 0.630 → 0.901 | 0.551 → 0.632 |
| high_inflation medium | 0.633 → 0.890 | 0.545 → 0.628 |
| tiny fixture | 0.898 → 0.898 (groups below 256) | 0.715 → 0.715 |

## Consequences
- The ground-truth test passes on baseline, high_inflation and tiny and is no longer an expected failure.
- The forest of baseline medium took 3.5 s instead of 1.8 s, measured with other simulations running on the machine (UNVERIFIED on an idle machine).
- The manifest's method settings show `max_samples: all`. The settings enter the run id (0058), so every run id changes.
- On all faulted claims, including those whose faults do not touch amounts (missing currency, unknown status, duplicates), the AUC stays near 0.63. Those faults belong to the quality checks, not to MT09.
