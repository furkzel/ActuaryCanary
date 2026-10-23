# MT09 Isolation forest anomaly flags

Specification: [MT09](../../spec/methods/MT09-isolation-forest-flags.yaml) · Decisions: [0043](../decisions/0043-anomaly-methods.md), [0061](../decisions/0061-isolation-forest-on-the-whole-group.md)

## Purpose

[MT08](MT08-robust-z-score-flags.md) looks at one movement at a time. MT09 looks at whole claims: a claim can be unusual because of the combination of its features (very high paid share yet still open, many negative payments, a long reporting delay) without any single movement standing out. The isolation forest scores how easily random splits isolate a claim from the others: anomalies are few and different, so they are isolated after few splits.

## Theory

For each claim at the cut-off, in the reporting currency at a constant rate, ten features are built: $\ln(1 + \text{incurred}^+)$, $\ln(1 + \text{paid}^+)$, paid over incurred (clipped to 0–2), months since the first valuation, the share of rows with a reserve change, the logarithm of the largest monthly payment, the largest absolute log reserve change, the number of negative paid flows, an open flag and, when the claims file is loaded, the reporting delay in days.

An isolation forest (Liu, Ting and Zhou, 2008) grows trees on random splits of random features. If a claim $x$ is isolated at average depth $E[h(x)]$ over the trees, its score is

$$s(x) = 2^{-E[h(x)] / c(\psi)}, \qquad c(\psi) = 2 H(\psi - 1) - \frac{2(\psi - 1)}{\psi}$$

where $\psi$ is the sample size per tree and $H$ the harmonic number; $c(\psi)$ is the average depth of an unsuccessful search in a binary tree and normalises the score. A score near 1 means easily isolated, near 0.5 average, near 0 deep inside the cloud. The platform flags the top share `contamination` (default 1 per cent) of each segment's claims, so at least one claim per scored segment is flagged whatever the data look like.

Claims are sorted by identifier before the forest is fitted and the seed is fixed (default 1, recorded in the run manifest), so the same data always give the same scores whatever the row order.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| Anomalous claims are few and differ from the rest on the chosen features. | The score histogram has a thin upper tail; flagged claims are reviewed against MT08 flags and against the feature values of the group medians (both are in the report). |

Segments are never mixed. Groups with fewer than 100 claims are not scored. By default every claim of the group goes into every tree: with the 256 of the original paper, a feature that is non-zero for a handful of claims in thousands (negative payments) is constant in most trees and never split on (decision 0061).

## What a flag is

A lead to review. The reason names the three features furthest from the group median. On the synthetic baseline the claims with injected faults rank higher than the others (an area under the ROC curve of at least 0.7 is required by the specification; the measured value is in decision 0061).

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

150 claims of one segment with the ten MT09 features drawn from a seeded standard normal distribution (seed 7), except that claim C0000 has a `log_incurred` of 25, far outside the rest. The forest has 50 trees (the default is 200; fewer keep the docs check fast), every claim in every tree and seed 1.

| Rank | Claim | Score | Flagged |
| --- | --- | --- | --- |
| 1 | C0000 | 0.58 | True |
| 2 | C0049 | 0.558 | True |
| 3 | C0127 | 0.543 | False |

The median score of the other 149 claims is 0.44 (a score near 0.5 means “no more isolated than average”, near 1 means “easily isolated”). With `contamination` 0.01 the top $\lceil 0.01 \times 150 \rceil = 2$ claims of the group are flagged: C0000, C0049. The second one is flagged only because the rule always flags that share of the group, not because it is far out (its score is 0.558, the outlier's 0.58); the flag of the first reads: “isolation score 0.5803 (rank 1 in its group); log_incurred 25.0 (group median -0.115); paid_share 1.512 (group median -0.141); reserve_change_share -1.639 (group median -0.03)”.

<!-- worked-example:end -->

## References

- Liu, F. T., Ting, K. M. and Zhou, Z.-H. (2008). Isolation Forest. *IEEE International Conference on Data Mining*.
