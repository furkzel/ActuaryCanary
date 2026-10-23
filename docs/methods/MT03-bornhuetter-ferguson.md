# MT03 Bornhuetter–Ferguson

Specification: [MT03](../../spec/methods/MT03-bornhuetter-ferguson.yaml) · Decisions: [0011](../decisions/0011-priors-selection-and-reserve-range.md), [0040](../decisions/0040-premium-based-methods.md)

## Purpose

For young origin periods the claims reported so far say little, and a factor of 2.5 or more applied to a small number amplifies noise. Bornhuetter–Ferguson keeps what is reported and adds only the share still to emerge, taken from an a priori expectation (prior loss ratio times earned premium) rather than from the noisy latest figure.

## Theory

With earned premium $P_i$, a prior loss ratio $ELR_i$ and the chain-ladder pattern of the same triangle:

$$U^{0}_i = ELR_i \cdot P_i, \qquad q_i = 1 - \frac{1}{CDF_{J_i}}, \qquad \hat U^{BF}_i = C_{i,J_i} + q_i \, U^{0}_i$$

$q_i$ is the share of the ultimate not yet reported (or paid, on a paid triangle). Two limits explain the method: with $q_i = 0$ the ultimate is the latest value; with a prior equal to the chain-ladder loss ratio the result equals the chain ladder. In between it is a credibility-style blend that weights the data by how developed the origin is.

On an incurred triangle the IBNR is exactly $q_i U^0_i$.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| The prior loss ratio is credible for each origin. | Compare it with the Cape Cod ratio ([MT04](MT04-cape-cod.md)) and with the chain-ladder loss ratios of mature origins. |
| The chain-ladder pattern describes the share still to emerge. | As for [MT02](MT02-chain-ladder.md). |
| Earned premium measures exposure consistently across origins. | Average premium (PR06) trend; rate changes in the assumptions register. |

## In the platform

Without a prior from the assumptions register the platform uses the Cape Cod loss ratio of the same group and labels it "data-derived prior" (decision 0011). The method needs accident or underwriting origins matched to earned premium; on report or first-valuation origins it does not run and says so. Premium by underwriting period is not built in version 1.0.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

The incurred triangle of the hand fixture (paid plus case reserve) with earned premium 400, 440, 480, 520 for the four origins, and a prior loss ratio of 0.6:

| Origin | 12 months | 24 months | 36 months | 48 months |
| --- | --- | --- | --- | --- |
| 2021 | 200 | 250 | 275 | 286 |
| 2022 | 220 | 260 | 286 |  |
| 2023 | 180 | 210 |  |  |
| 2024 | 190 |  |  |  |

The chain ladder on this triangle gives the cumulative factors 1.3728, 1.144, 1.04, 1 for ages 12 to 48 months. Per origin:

| Origin | Premium | Prior ultimate | Unreported share q | Latest | BF ultimate | Chain ladder |
| --- | --- | --- | --- | --- | --- | --- |
| 2021 | 400 | 240 | 0 | 286 | 286 | 286 |
| 2022 | 440 | 264 | 0.0385 | 286 | 296.1538 | 297.44 |
| 2023 | 480 | 288 | 0.1259 | 210 | 246.2517 | 240.24 |
| 2024 | 520 | 312 | 0.2716 | 190 | 274.7273 | 260.832 |

For 2024: $q = 1 - 1/1.3728 = 0.2716$, prior ultimate $0.6 \times 520 = 312$, so the ultimate is $190 + 0.2716 \times 312 = 274.7273$. The total BF ultimate is 1,103.13 against 1,084.51 for the chain ladder.

<!-- worked-example:end -->

## References

- Bornhuetter, R. L. and Ferguson, R. E. (1972). The Actuary and IBNR. *Proceedings of the Casualty Actuarial Society*.
- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, the chapter on the Bornhuetter–Ferguson method.
