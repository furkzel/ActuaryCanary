# MT10 Ultimate selection

Specification: [MT10](../../spec/methods/MT10-ultimate-selection.yaml) · Decisions: [0011](../decisions/0011-priors-selection-and-reserve-range.md), [0055](../decisions/0055-methods-in-the-reserving-module.md)

## Purpose

Several methods give several ultimates for the same origin. The report and the reserve range need one. MT10 chooses it by a plain rule and records why, so the choice can be read, challenged and overridden.

## Theory

The maturity of origin $i$ is the share of its ultimate that the selected chain-ladder pattern says is already in the triangle:

$$m_i = \frac{1}{CDF_{J_i}}, \qquad \hat U^{\mathrm{sel}}_i = \begin{cases} \hat U^{BF}_i & m_i < 0.5 \text{ and BF available} \\ \hat U^{CL}_i & \text{otherwise} \end{cases}$$

Below a maturity of 0.5 ($m$ = `bf_below_maturity`, an owner decision, record 0011) the reported claims are too thin to extrapolate by factors alone, so [Bornhuetter–Ferguson](MT03-bornhuetter-ferguson.md) takes over; from there on the [chain ladder](MT02-chain-ladder.md) decides. If Bornhuetter–Ferguson is not available for an immature origin (no premium, report-date origins), the chain ladder is used and the reason is recorded. Overrides from the assumptions register replace the default per origin, each with who, when and why.

The selection is made on the incurred triangle by default (`measure: incurred`). Its prior for Bornhuetter–Ferguson is the Cape Cod ratio of that triangle (decision 0055).

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| Below the maturity threshold the reported claims are too thin to extrapolate by factors alone. | Compare chain ladder and Bornhuetter–Ferguson per origin; large gaps at low maturity confirm the switch. The report shows every method's ultimate beside the selected one. |

The threshold is a convention, not a theorem: the method is deliberately simple so that the selection is explainable. A different judgement (for instance Cape Cod for a young origin, or an expected loss ratio) is entered as an override.

## Outputs

Selected ultimate, unpaid and IBNR per origin with the method chosen and the reason; the maturity of each origin. The selected ultimate feeds the ultimate loss ratio (RT01), the reserve estimate in the key findings and the Mack range ([MT06](MT06-mack.md)).

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

The paid triangle of the hand fixture, premium 400, 440, 480, 520 and a prior loss ratio of 0.6. The maturity of an origin is $1/CDF$, the share of its ultimate that the triangle says has been paid. Origins below 0.5 take Bornhuetter–Ferguson. The platform selects on the incurred triangle, where even the youngest origin of this fixture has a maturity of 0.728 and so keeps the chain ladder; the paid triangle is used here because it shows the switch. The last two columns show an override of origin 2023 to Bornhuetter–Ferguson, as a user would record it in the assumptions register:

| Origin | Maturity | Chain ladder | BF | Default choice | Default ultimate | With override | Ultimate with override |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | 1 | 220 | 220 | chain ladder | 220 | chain ladder | 220 |
| 2022 | 0.909 | 281.6 | 280 | chain ladder | 281.6 | chain ladder | 281.6 |
| 2023 | 0.758 | 250.8 | 259.82 | chain ladder | 250.8 | Bornhuetter–Ferguson | 259.82 |
| 2024 | 0.399 | 326.04 | 317.6 | Bornhuetter–Ferguson | 317.6 | Bornhuetter–Ferguson | 317.6 |

Reason recorded for 2024: maturity 0.399 below 0.5. Reason for 2023 with the override: override in the assumptions register.

<!-- worked-example:end -->

## References

- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, chapter 14.
