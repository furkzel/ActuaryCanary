# MT04 Cape Cod

Specification: [MT04](../../spec/methods/MT04-cape-cod.yaml) · Decisions: [0011](../decisions/0011-priors-selection-and-reserve-range.md), [0040](../decisions/0040-premium-based-methods.md)

## Purpose

Bornhuetter–Ferguson needs a prior loss ratio that someone must supply. Cape Cod estimates it from the data: how much was reported against how much premium the pattern says has "had time" to produce claims. It is Bornhuetter–Ferguson with a prior learned from all origins of the group, and it is the default prior of [MT03](MT03-bornhuetter-ferguson.md) and [MT05](MT05-expected-loss-ratio.md) in the platform.

## Theory

The used-up premium of origin $i$ is the premium multiplied by the share of the ultimate that the pattern has reached, $P^u_i = P_i / CDF_{J_i}$. The group's expected loss ratio is reported claims over used-up premium, and each ultimate follows the Bornhuetter–Ferguson form:

$$P^{u}_i = \frac{P_i}{CDF_{J_i}}, \qquad ELR^{CC} = \frac{\sum_i C_{i,J_i}}{\sum_i P^{u}_i}, \qquad \hat U^{CC}_i = C_{i,J_i} + \Big(1 - \frac{1}{CDF_{J_i}}\Big) ELR^{CC} P_i$$

The platform uses no trend and no decay (every origin carries the same weight), which keeps the method checkable against the chainladder package with matching settings.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| One expected loss ratio holds for all origins of the group. | Chain-ladder loss ratios of mature origins show no trend; rate changes and claims inflation are small or adjusted (see [MT07](MT07-inflation-adjusted-chain-ladder.md)). |
| The chain-ladder pattern describes reporting. | As for [MT02](MT02-chain-ladder.md). |

The diagnostics show the chain-ladder loss ratio of each origin next to $ELR^{CC}$. A clear trend there means Cape Cod will understate the young origins on a deteriorating book and overstate them on an improving one.

## In the platform

The method runs per group on the incurred and on the paid triangle, each with its own ratio. It needs accident or underwriting origins matched to earned premium and does not run otherwise.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

The hand fixture with earned premium 400, 440, 480, 520. No prior is given: the data provide it.

On the incurred triangle:

| Origin | Premium | CDF | Used-up premium | Latest | Cape Cod ultimate |
| --- | --- | --- | --- | --- | --- |
| 2021 | 400 | 1 | 400 | 286 | 286 |
| 2022 | 440 | 1.04 | 423.0769 | 286 | 296.1448 |
| 2023 | 480 | 1.144 | 419.5804 | 210 | 246.2194 |
| 2024 | 520 | 1.3728 | 378.7879 | 190 | 274.6518 |

Expected loss ratio: $972 / 1,621.45 = 0.5995$. Total ultimate 1,103.02.

On the paid triangle:

| Origin | Premium | CDF | Used-up premium | Latest | Cape Cod ultimate |
| --- | --- | --- | --- | --- | --- |
| 2021 | 400 | 1 | 400 | 220 | 220 |
| 2022 | 440 | 1.1 | 400 | 256 | 279.2244 |
| 2023 | 480 | 1.32 | 363.6364 | 190 | 257.5618 |
| 2024 | 520 | 2.508 | 207.3365 | 130 | 311.5354 |

Expected loss ratio: $796 / 1,370.97 = 0.5806$. Total ultimate 1,068.32.

The incurred ratio, 0.5995, is close to the prior of 0.6 that the Bornhuetter–Ferguson example assumes; the paid ratio, 0.5806, is lower: the two triangles carry different information and each gives its own ratio.

<!-- worked-example:end -->

## References

- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, chapter 10.
