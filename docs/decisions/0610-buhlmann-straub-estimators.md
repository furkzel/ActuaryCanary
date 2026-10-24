# 0610 — Bühlmann–Straub: the estimators are named

## Context
Record 0272 left Bühlmann–Straub without a reference because MT20 named no estimators for the structural parameters, and the choice changes the weights.

## Decision
Chosen by the owner on 2026-10-24: MT20 names the classical unbiased estimators (Bühlmann and Gisler 2005): the pooled within-cell variance, and the between-cell variance estimated from the weighted totals. A negative between-cell variance is truncated to zero, which gives the credibility factor zero for every cell. MT20 is edited (version 0.2.0, still a draft) with the formulas. They need several observation periods per cell (cell by calendar year), because the within-cell variance cannot be estimated from one period; the spec now says so and falls back to limited fluctuation when a cell has fewer than two periods. That reading is the only one under which the named estimators exist; the owner may change it when reading the draft.

## Consequences
- The hand-worked fixture is built by the item that implements MT20 (P33), not here. No number is frozen for Bühlmann–Straub yet; `coverage.yaml` keeps the open item, reworded.
- Reference tables for expected rates are still the owner's open decision before P32.
