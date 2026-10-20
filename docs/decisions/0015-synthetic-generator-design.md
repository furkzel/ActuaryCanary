# 0015 — Synthetic generator design

## Context
P02 needs data in the version 1.0 input format whose true answers are known. The owner chose mode A, a seeded generator (2026-10-20).

## Decision
- Scenarios are files in `synthetic/scenarios/`. `baseline.yaml` is the former `synthetic/truth.yaml`; the other four start from it with `extends: baseline` (dictionaries merge, lists are replaced). Files are validated with pydantic; a misspelt parameter is an error.
- One seed per scenario. Every stage and line draws from its own stream, derived from the seed and the stage's name, so changing one line never moves the draws of another.
- Money mechanics: a claim has a cost at base-date prices; a payment is cost × share × claims index at the payment date (CPI × superimposed inflation; for foreign currency, foreign inflation × superimposed inflation ÷ starting rate). A case reserve is the adjuster's estimate of the remaining cost at that day's prices × (1 + bias) × lognormal noise, revised on a fixed cycle; the bias can change on a date. A reopening is a second period with its own payment and reserves; a nil claim carries a reserve for a latent cost until it closes.
- Sums insured and premiums move with the price index at the policy start. Quota shares apply first, then excess of loss per claim or per event, on what the insurer keeps.
- The truth is the whole simulated world, including payments after the cut-off (prices and exchange rates continue at the last listed rate). Faults and mess change the files only, never the truth.
- Each scenario writes the six spreadsheets, `canonical/*.parquet` (what recognition should return), and `truth/*.csv`. Files are byte-for-byte reproducible (fixed workbook properties).
- The mess layer takes headers and labels from the alias dictionaries AL01 and AL02, so recognition tests use the product's own vocabulary.
- `check.py` reads a folder back, undoes the layout with the truth files and lists every violation of the data rules; tests require that the violations are exactly the injected faults.

## Consequences
- Every method can be scored against `ultimates.csv`, `ibnr_by_valuation.csv`, `development_pattern.csv`, `inflation.csv` and `frequency_severity.csv`.
- Stage-level streams make scenarios comparable: `high_inflation` has the same claims at base prices as `baseline`.
- Tiny fixtures are committed; a slow test fails when the generator no longer writes them, and `just synth-fixtures` refreshes them.
