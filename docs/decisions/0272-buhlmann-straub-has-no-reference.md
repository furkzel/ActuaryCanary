# 0272 — No Bühlmann–Straub reference yet

## Context
MT20 says the Bühlmann–Straub structural parameters are "estimated from the cells, non-negative" and gives only kappa = s²/a. With one period per cell the within-cell variance cannot be estimated from the data, so a rule (Poisson variance equal to the portfolio A/E, or another) has to be chosen, and the choice changes the weights.

## Decision
The credibility fixture covers the limited-fluctuation weight (fully specified: probability 0.9, tolerance 0.05) and the Garwood intervals only. No number is frozen for Bühlmann–Straub. This is a specification gap for the owner, not a test gap to fill by guessing.

## Consequences
- `coverage.yaml` lists it as an open item of MT20; P33 should not build Bühlmann–Straub before the spec names the estimators.
- Expected deaths come from invented reference rates per age band; real reference tables are the owner's open decision before P32.
