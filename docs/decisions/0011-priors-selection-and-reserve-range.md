# 0011 — Priors, ultimate selection and the reserve range

## Context
Bornhuetter–Ferguson needs a prior loss ratio, loss ratios need one selected ultimate per origin, and the Mack standard error belongs to plain chain ladder only.

## Decision
Chosen by the owner on 2026-10-20:
- Without a user prior, Bornhuetter–Ferguson and the expected loss ratio method use the Cape Cod ratio of the same segment and line, labelled "data-derived prior" (MT03, MT05).
- Default selection (MT10): chain ladder where the reported share 1/CDF is at least 0.5, Bornhuetter–Ferguson below it; per-origin overrides go into the assumptions register.

Chosen in this work item:
- When the selection is not the Mack chain ladder (other averages, exclusions, a tail or BF), the Mack coefficient of variation is applied to the selected reserve and labelled (MT06).
- Reserve distribution lognormal with the Mack mean and standard error; VaR at 99.5 per cent and TVaR at 99 per cent by default, labelled as an approximation.

## Consequences
- Every origin has a selected ultimate whenever chain ladder runs.
- Ranges for selections other than chain ladder are approximate until the tier B bootstrap exists.
