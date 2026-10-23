# MT02 Chain ladder

Specification: [MT02](../../spec/methods/MT02-chain-ladder.yaml) · Decisions: [0038](../decisions/0038-chain-ladder-selection-and-exclusions.md), [0039](../decisions/0039-diagnostic-thresholds.md)

## Purpose

The chain ladder projects the cumulative claims of every origin period to ultimate with age-to-age factors learned from the triangle. The difference between the ultimate and what is already paid is the unpaid amount; against incurred it is the IBNR. It is the workhorse of reserving: simple, transparent and the base of Bornhuetter–Ferguson, Cape Cod, Mack and the inflation-adjusted method.

## Theory

Let $C_{i,j}$ be the cumulative amount of origin $i$ at development index $j$ (origins $0$ to $I-1$, indices $0$ to $J-1$). The link ratio of a pair of observed cells is

$$F_{i,j} = \frac{C_{i,j+1}}{C_{i,j}}$$

The factor of column $j$ averages the usable link ratios $A_j$ (origins with both cells, not excluded, inside the latest $n$ diagonals if asked). The volume-weighted average, the default, and the simple average are

$$f_j^{\mathrm{vw}} = \frac{\sum_{i \in A_j} C_{i,j+1}}{\sum_{i \in A_j} C_{i,j}}, \qquad f_j^{\mathrm{simple}} = \frac{1}{|A_j|} \sum_{i \in A_j} F_{i,j}$$

With a tail factor $\tau$ (default 1.0: no development after the last observed age) the cumulative development factors and the ultimate of origin $i$ with latest index $J_i$ are

$$CDF_j = \tau \prod_{k=j}^{J-2} f_k, \qquad \hat U_i = C_{i,J_i} \cdot CDF_{J_i}$$

Unpaid is $\hat U_i$ minus paid; IBNR is $\hat U_i$ minus incurred. The projected lower triangle is $\hat C_{i,k+1} = \hat C_{i,k} f_k$.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| Future development follows the same age-to-age factors as the past. | Link ratios stable down each column (coefficient of variation in the diagnostics); no trend by origin. |
| Origins are comparable: no change in case reserving, payment speed or mix. | Paid-to-incurred ratios stable along diagonals (CL10); case reserve run-off stable (CL11). |
| No calendar-period effect such as an inflation shock. | Mean standardised residual per diagonal close to zero; if not, see [MT07](MT07-inflation-adjusted-chain-ladder.md). |

The platform also warns when the last factor is still above 1.05 with a tail of 1.0 (development is not finished), when a factor rests on one or two link ratios, when a usable link ratio has a zero denominator, and always when there are fewer than eight origin periods (thin evidence, decisions 0039 and 0064).

## Judgement

The user can select a factor for a column, exclude a link ratio or change the average. Every such choice goes into the assumptions register with who, when, why and the alternative (the average it replaced), and into the run manifest.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

The paid triangle of the hand fixture (cumulative, annual origins, ages in months):

| Origin | 12 months | 24 months | 36 months | 48 months |
| --- | --- | --- | --- | --- |
| 2021 | 90 | 170 | 200 | 220 |
| 2022 | 110 | 210 | 256 |  |
| 2023 | 100 | 190 |  |  |
| 2024 | 130 |  |  |  |

Link ratios $F_{i,j} = C_{i,j+1} / C_{i,j}$:

| Origin | 12-24 months | 24-36 months | 36-48 months |
| --- | --- | --- | --- |
| 2021 | 1.8889 | 1.1765 | 1.1 |
| 2022 | 1.9091 | 1.219 |  |
| 2023 | 1.9 |  |  |
| 2024 |  |  |  |

The volume-weighted factor of a column divides the sum of the later cells by the sum of the earlier cells of the origins that have both. For the first column $(170 + 210 + 190) / (90 + 110 + 100) = 570 / 300 = 1.9$; the second $(200 + 256) / (170 + 210) = 1.2$; the third $220 / 200 = 1.1$. The averages side by side:

| Average | 12-24 months | 24-36 months | 36-48 months |
| --- | --- | --- | --- |
| Volume-weighted (the default) | 1.9 | 1.2 | 1.1 |
| Simple average | 1.8993 | 1.1978 | 1.1 |
| Latest two diagonals | 1.9048 | 1.2 | 1.1 |

Cumulative factors to ultimate with the tail factor 1.0, and the ultimates:

| Origin | Latest paid | CDF | Ultimate | Unpaid |
| --- | --- | --- | --- | --- |
| 2021 | 220 | 1 | 220 | 0 |
| 2022 | 256 | 1.1 | 281.6 | 25.6 |
| 2023 | 190 | 1.32 | 250.8 | 60.8 |
| 2024 | 130 | 2.508 | 326.04 | 196.04 |

The total ultimate is 1,078.44 and the total unpaid 282.44 (latest paid 796). The test suite checks every number of this example against `tests/fixtures/hand/expected.yaml`.

<!-- worked-example:end -->

## References

- Mack, T. (1993). Distribution-free calculation of the standard error of chain ladder reserve estimates. *ASTIN Bulletin* 23.
- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, chapter 7.
