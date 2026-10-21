# 0021 — Truth currency, foreign-claim scale, and magnitudes of high_inflation and large_loss

## Context
Gate G0 (record 0019) found three things: USD and EUR rows of `truth/ultimates.csv` gave ratios near 0.1; `high_inflation` gave a third-party liability ratio of 4.285 and `large_loss` a property ratio of 3.915 at medium; two records were numbered 0007.

## Finding 1: currency
The suspicion in 0019 (premium in TRY, claims in the row currency) was wrong. Read in the code and confirmed on the baseline medium output:
- `earned_premium` was already in the currency of the row: sums insured of foreign policies are divided by the exchange rate and the premium is a rate on them (`portfolio.py`).
- The claims side was wrong. A foreign claim's cost at base prices was divided by the starting rate when drawn (`cost = body / fx0`) and the foreign claims index divided by it again (`index_for`, and the sum-insured cap). Foreign payments came out too small by the starting rate (2.95 for USD, 3.25 for EUR). Fixed: the index of a foreign claim is foreign inflation times superimposed inflation, as the cost is already in the claim's currency.

Truth files now state the currency of every money column. `truth/money_columns.csv` lists file, column, currency (`row` = the `currency` column of that row; `reporting` = TRY) and, for TRY columns, how it was converted. Columns in TRY carry `try` in their name; every other money column is in the row currency. `ultimates.csv` gained `fx_cutoff_rate` (TRY per unit of the row currency at the cut-off, the constant development rate of CV01) and `earned_premium_try_at_cutoff_rate`, so a premium and a claim amount can be compared in either currency. `frequency_severity.csv`: `mean_base_severity` and `expected_base_severity` were TRY at base prices and are renamed `..._try`. Large-loss anomaly details say TRY. The data checker does not read these files; the consumers were the truth tests, updated.

Tests: `tests/synthetic/test_truth_currency.py` — every column of every truth table is declared money or not money; reporting columns equal row columns times the cut-off rate; on a scenario with 50 per cent foreign motor-own-damage policies, earned premium by line and currency lies between 0.4 and 1.0 of the written premium in the feed (a TRY amount labelled USD would be 20 to 30 times larger), and paid at the cut-off by currency equals the paid in the claim valuation feed; USD and EUR loss ratios are within a factor of 2 of the TRY ratio (the old double division gave 0.15 to 0.35 of it; the test fails on it, checked).

Baseline PROPERTY at medium, ratio ultimate gross ÷ earned premium, ten years:

| Rows | Before | After |
| --- | --- | --- |
| USD | 0.103 | 0.305 |
| EUR | 0.126 | 0.410 |
| TRY | 0.796 | 0.796 |

Foreign rows stay below TRY for reasons that belong to the world: catastrophe events hit TRY policies only, foreign claims inflate at 2 to 3 per cent so they gain nothing from the TRY price lag, and the foreign premium follows the exchange-rate random walk. On the 50 per cent test portfolio without cat events and with a quiet rate, USD and EUR are 0.9 and 0.6 times the TRY ratio.

## Finding 2: scenario magnitudes
No generator change except a rule that was missing: `lines.<LINE>.large_events` (rate per exposure year, cost distribution at base prices, uncapped, own random stream, listed in `anomalies.csv` as `large_loss_event`). A scenario that does not use it is unchanged, `truth/scenario.yaml` included. The three fixed-date shocks of `large_loss` are removed from the scenario; the `large_claims` option remains and is tested.

- `high_inflation`: price path unchanged; superimposed inflation MOTOR_OD 0.08 → 0.05, PROPERTY 0.05 → 0.035, MOTOR_TPL 0.12 → 0.05 (the baseline value); MOTOR_TPL premium 9,500 → 12,000. The premium still follows prices at policy start and does not follow superimposed inflation; the higher TPL premium is a one-level tariff response, not a time-varying pass-through (that would need a premium trend in the generator; not built).
- `large_loss`: tails MOTOR_TPL 0.03 → 0.015 (alpha 1.5 → 1.8), PROPERTY 0.03 → 0.02 (alpha 1.3 → 1.5); large events MOTOR_TPL 2e-5 per exposure year, lognormal median 6,000,000 sigma 0.6; PROPERTY 1.4e-4, median 3,500,000 sigma 0.6. About 3 to 4 and 4 to 5 events per ten years at medium.

Measured 2026-10-21 on `truth/ultimates.csv`, TRY rows, ten-year ultimate gross ÷ earned premium (the 0019 figure pooled all currencies; the PROPERTY pooled figure after the fix is 0.791 baseline, 1.123 high_inflation, 1.075 large_loss):

| Scenario, medium | | MOTOR_OD | MOTOR_TPL | PROPERTY | GROUP_TERM_LIFE |
| --- | --- | --- | --- | --- | --- |
| baseline, messy_headers, reserve_bias_change | before | 0.808 | 0.957 | 0.789 | 0.595 |
| | after | 0.808 | 0.957 | 0.796 | 0.595 |
| high_inflation | before | 1.361 | 4.285 | 1.274 | 0.596 |
| | after | 1.068 | 1.387 | 1.130 | 0.596 |
| | target | 0.90–1.30 | 1.20–2.00 | 0.90–1.30 | unchanged |
| large_loss | before | 0.808 | 1.477 | 3.915 | 0.595 |
| | after | 0.808 | 1.205 | 1.083 | 0.595 |
| | target | unchanged | 1.10–1.50 | 1.00–1.60 | unchanged |

Large size, TRY rows, written files, scenario seed (baseline large was not re-run after the fix; 0018 gave 0.785, 1.025, 0.870, 0.564 before it):

| Scenario | MOTOR_OD | MOTOR_TPL | PROPERTY | GROUP_TERM_LIFE |
| --- | --- | --- | --- | --- |
| high_inflation | 1.034 | 1.601 | 1.171 | 0.558 |
| large_loss | 0.785 | 1.202 | 1.126 | 0.564 |

MOTOR_TPL in `high_inflation` by accident year, 2016 … 2025, medium:
- Before: 1.572, 1.289, 1.517, 1.977, 4.276, 4.763, 4.934, 4.615, 6.657, 3.210
- After: 0.763, 0.607, 0.685, 0.811, 1.656, 1.664, 1.763, 1.601, 1.969, 1.013

Sampling spread (in memory, the scenario seed plus 0 to 5 at medium, 0 to 3 at large; mean and range; seed 0 is the written file):
- `high_inflation` medium: OD 1.03 (0.99–1.10), TPL 1.61 (1.39–2.02), PROPERTY 1.15 (0.89–1.34); large: OD 1.04, TPL 1.76 (1.58–1.99), PROPERTY 1.20 (1.17–1.22).
- `large_loss` medium: TPL 1.21 (1.06–1.40), PROPERTY 1.22 (0.89–1.65); large: TPL 1.35 (1.20–1.53), PROPERTY 1.17 (1.13–1.25).
- `large_loss` tiny (12 seeds): TPL 1.16 (0.48–2.68), PROPERTY 1.96 (0.18–7.14). The expected number of large events at tiny is below one, so a single event decides the ratio. Ratios are comparable in expectation at medium and large, not at tiny.

Baseline output is byte-identical across the scenario change (all 27 files of the baseline medium folder compared before and after; the only differences were two files that name a truth column's wording, edited in between). The tiny fixtures and `examples/` were regenerated for the claim-scale fix: `claim_valuations`, `expenses`, the truth tables and manifests changed, `policies`, `premiums`, `claims` and `market` did not.

## Finding 3: numbering
Two records were numbered 0007. Kept: `0007-benchmark-reference-values.md` (spec MT06 cites it). `0007-specification-format.md` became `0020-specification-format.md`. References to it: none in code, specs or other records; the P01 log line of HANDOVER.md ("records 0007–0014") is history and was left.

## Consequences
- Anything that compared foreign-currency claims or loss ratios from earlier output must be regenerated.
- A reader of `truth/ultimates.csv` adds amounts only within one `currency`, or uses the `_try` columns.
- Large-loss tests at tiny size use an explicit rate or the `large_claims` option, not the scenario file.
- UNVERIFIED: baseline large after the fix; messy_headers and reserve_bias_change at large; Excel reading of the spreadsheets.
