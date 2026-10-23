# RT01 and RT02 Loss ratio and combined ratio

Specifications: [RT01](../../spec/measures/RT01-loss-ratio.yaml), [RT02](../../spec/measures/RT02-combined-ratio.yaml), [EX01](../../spec/measures/EX01-commission-ratio.yaml), [EX02](../../spec/measures/EX02-expense-ratio.yaml), [PR02](../../spec/measures/PR02-earned-premium.yaml)

Profitability is a tier A analysis in the blueprint (section 9.1) but it is built from measures, not from a method with a `MT` identifier; this note stands for module M05. The descriptive profiling and trend measures of M01 to M03 (claim counts, frequency, severity, reporting delay, settlement) are described by their own specifications in `spec/measures/`.

## Purpose

Does the book make money, by line and period? A paid or incurred loss ratio answers that wrongly for young periods: their claims have not been reported yet. The ultimate loss ratio puts every accident period on the same footing by using the selected ultimate ([MT10](MT10-ultimate-selection.md)); adding the expense and commission ratios gives the combined ratio.

## Theory

By accident period $i$, with $L^m_i$ the paid (CL01), incurred (CL03) or selected ultimate claims as of the cut-off and $EP(i)$ the earned premium (PR02) of the same segment and line:

$$LR^{m}(i) = \frac{L^{m}_i}{EP(i)}, \quad m \in \{\mathrm{paid}, \mathrm{incurred}, \mathrm{ultimate}\}$$

The commission ratio is commission earned over gross earned premium, $CM(Q) = EC(Q)/EP^{\mathrm{gross}}(Q)$ (EX01), and the expense ratio is acquisition (other than commission) and administration expenses over gross earned premium, $ER(Q) = (X^{\mathrm{ACQ}}(Q) + X^{\mathrm{ADM}}(Q))/EP^{\mathrm{gross}}(Q)$ (EX02). The combined ratio of an accident period is

$$COR(i) = LR^{\mathrm{ultimate}}(i) + ER(i) + CM(i)$$

with the expense and commission ratios taken for the calendar period that has the same dates as the accident period. A combined ratio above 1 means an underwriting loss before investment income. The change of a ratio against the previous period is shown with each tile of the report, and the key findings call out a clear rise in the ultimate loss ratio.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| Earned premium is right. | Reconcile PR01 (written) and PR03 (unearned) with the books; look at average premium (PR06) and cancellations (PR04) in module M02. |
| The selected ultimate is reasonable. | The reserving page of the line: methods side by side, diagnostics, the Mack range. |
| Expenses are allocated to the line they belong to. | Expenses without a line cannot be allocated; the report states the level at which a ratio is available. |

A ratio with zero or negative earned premium is not computed. The report states that all of these are indicative: not an official reserve, price or financial statement figure.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

Earned premium, paid and incurred of the hand fixture; the ultimate is the chain ladder on the incurred triangle (the default selection for these origins). The expense and commission ratios are not in the fixture: the example assumes 0.08 and 0.12 for every origin to show the sum.

| Origin | Earned premium | Paid | Paid ratio | Incurred | Incurred ratio | Ultimate | Ultimate ratio | Combined ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | 400 | 220 | 0.55 | 286 | 0.715 | 286 | 0.715 | 0.915 |
| 2022 | 440 | 256 | 0.5818 | 286 | 0.65 | 297.44 | 0.676 | 0.876 |
| 2023 | 480 | 190 | 0.3958 | 210 | 0.4375 | 240.24 | 0.5005 | 0.7005 |
| 2024 | 520 | 130 | 0.25 | 190 | 0.3654 | 260.83 | 0.5016 | 0.7016 |

Trend: the ultimate loss ratio moves from 0.715 for 2021 to 0.5016 for 2024, a change of -21.3 percentage points. The paid ratio of the newest origin looks low only because its claims are not yet paid; the ultimate ratio puts all origins on the same footing.

<!-- worked-example:end -->

## References

- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society (the loss ratio as the base of the premium-based methods).
