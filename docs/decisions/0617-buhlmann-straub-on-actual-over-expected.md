# 0617 — Bühlmann-Straub on actual over expected

## Context
Record 0610 named the estimators of the structural parameters but left the variable as the crude rate A / E per cell with the exposure as weight. Crude rates differ by age by a factor of many, so pulling them towards a portfolio mean is meaningless.

## Decision
MT20 0.3.0 keeps the estimators of 0610 and changes the variable: X(c,t) = A(c,t) / D(c,t), with D(c,t) the expected decrements of the cell in calendar year t from the reference table, and the weight w(c,t) = D(c,t). The credibility-weighted ratio is Z(c) X(c) + (1 - Z(c)) X, with X the collective A/E. The method exists only with a reference table; without one the credibility is `none` and crude rates are shown. The exposure symbol is Ex and D is the expected decrements wherever E stood for both.

The rule of 0610 that each cell is observed in at least two calendar years stays as the owner's reading; the pooled estimator itself only needs the sum of (T(c) - 1) to be positive, and the spec says so.

## Consequences
- Supersedes the variable of 0610, not its estimators; the hand-worked fixture of P33 uses ratios A / D with weights D.
- Needs the reference tables the owner has still to decide before P32.
