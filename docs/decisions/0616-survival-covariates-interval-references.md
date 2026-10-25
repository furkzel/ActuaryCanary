# 0616 — Survival analysis: size class at report, log-log interval, what the references freeze

## Context
The draft MT19 named the size class of CV08 as a Cox covariate without saying when it is read, wrote the log-log interval only in words, and promised references for every output of the Cox model.

## Decision
MT19 0.3.0:
- The size class covariate is the class at report (incurred at the first valuation, CV08 bands). The class at the cut-off or at closing depends on the outcome and is allowed only as a descriptive grouping of Kaplan-Meier curves, labelled so.
- The log-log interval is S(t)^(exp(+-z sigma / |ln S(t)|)) with sigma = sqrt(sum d / (n (n - d))), the Greenwood sum; the plus sign gives the lower limit.
- The references freeze coefficients, standard errors, log-likelihoods and the overall tests. The Grambsch-Therneau test, the concordance and the baseline survival have no frozen reference and are information until one is frozen from R (`cox.zph`, `concordance`). The spec and the README of the references say so.

## Consequences
- A later reference item freezes those three from R and moves them out of information.
- The planner recomputed the Cox references (both tie rules) and the Kaplan-Meier hand fixture independently; they equal the frozen values.
