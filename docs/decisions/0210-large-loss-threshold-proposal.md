# 0210 — Large-loss threshold: an extreme-value proposal, open for the owner

## Context
Blueprint 18.2 leaves the default large-loss threshold rule open. Record 0010 chose the 99th percentile per segment and line (CV08) and named an extreme-value threshold as the possible tier B replacement. MT18 needs a threshold rule that is automatic and reproducible.

## Decision (proposed, draft; not in force)
- In MT18, the threshold of a segment and line is chosen by ForwardStop (Bader, Yan and Zhang 2018). Anderson–Darling tests of generalised Pareto fits are run at candidate quantiles from 0.80 to 0.99, with p-values by parametric bootstrap, a false discovery rate of 0.10 and at least 50 excesses.
- If adopted, CV08 would use the MT18 threshold. It would keep its own rules: catastrophe by event code, fewer than 100 non-nil claims falls back to the segment, a fixed threshold in the assumptions register replaces the rule, and the class is fixed per run.
- Until the owner decides, CV08 stays at the 99th percentile. MT18 reports the proposed threshold beside the one in force, with the share of claims and incurred above each.

## Consequences
- An extreme-value threshold changes the LARGE share per line: often fewer large claims on light-tailed lines and more on heavy-tailed ones. CL06, CL12, M06 and the run id move when it is adopted.
- The bootstrap p-values make MT18 slower than a percentile (around 6,000 refits per group at the defaults). The performance budget of the severity and extreme values item must cover it.
