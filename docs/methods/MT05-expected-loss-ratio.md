# MT05 Expected loss ratio method

Specification: [MT05](../../spec/methods/MT05-expected-loss-ratio.yaml) · Decisions: [0011](../decisions/0011-priors-selection-and-reserve-range.md), [0040](../decisions/0040-premium-based-methods.md)

## Purpose

For the newest origin periods, when almost nothing has been reported, the best guide to the final cost may be the premium and a loss ratio set in advance. The expected loss ratio method does exactly that and nothing more. It is the limiting case of [Bornhuetter–Ferguson](MT03-bornhuetter-ferguson.md) with no weight on the reported claims.

## Theory

$$\hat U^{ELR}_i = ELR_i \cdot P_i, \qquad \mathrm{IBNR}_i = \hat U^{ELR}_i - C^{\mathrm{inc}}_{i,J_i}$$

$ELR_i$ comes from the assumptions register; without an entry the platform uses the Cape Cod ratio of the group ([MT04](MT04-cape-cod.md)) and labels it "data-derived prior". The IBNR may be negative: when reported claims already exceed the expectation the method says so rather than hiding it.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| The expected loss ratio is a better guide than the claims reported so far. | Use it only for the newest origins; compare with Bornhuetter–Ferguson and chain ladder. A negative IBNR on an older origin is the warning that the assumption fails there. |

## In the platform

The platform flags every origin with a negative IBNR. In the default selection ([MT10](MT10-ultimate-selection.md)) this method does not decide an ultimate; it is shown beside the others so that the spread between methods is visible.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

Earned premium 400, 440, 480, 520 and an expected loss ratio of 0.6; the incurred amounts are those of the hand fixture.

| Origin | Premium | Expected ultimate | Incurred to date | IBNR | Chain ladder ultimate |
| --- | --- | --- | --- | --- | --- |
| 2021 | 400 | 240 | 286 | -46 | 286 |
| 2022 | 440 | 264 | 286 | -22 | 297.44 |
| 2023 | 480 | 288 | 210 | 78 | 240.24 |
| 2024 | 520 | 312 | 190 | 122 | 260.832 |

The two oldest origins show a negative IBNR (-46 and -22): they have already incurred more than 60 per cent of premium, and the method ignores that. The platform flags this and the note's advice stands: use the method only for the newest origins.

<!-- worked-example:end -->

## References

- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, chapter 8.
