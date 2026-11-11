# 0371 — MOTOR_TPL: the truth and the development pattern differ in basis, not in the claims

## Context
Records 0063, 0285 and 0624 found that `ultimates.csv` leaves 28 % of the MOTOR_TPL 2016 ultimate unpaid after ten years while `development_pattern.csv` says 1.9 %. Measured on `baseline medium` (seed 20261013, written 2026-11-10 outside the repository) with a read-only script, one pass per candidate.

## Findings
- **Cause: the way the truth is computed.** `ultimate_gross` and `paid_at_cutoff` are nominal: every payment at the claims-inflation index of its payment day, payments after the cut-off included (the CPI goes on at the last listed rate, 33 %, past 2025). `paid_share` and `incurred_share` of the pattern are inflation-free: payments at base-date prices. For accident year 2016 the share paid after the cut-off is 1.88 % in base-date prices and 28.09 % in prices of the day: those payments carry an index of 30.3 against 1.49 for the payments made before the cut-off. The two files are right on their own bases and silent about the basis; nothing in the pattern could reproduce `ultimates.csv`.
- **Settlement delays: not the cause.** The base-price tail of 1.9 % is the 3650-day cap on report-to-close time (`max_settlement_days`) plus reopenings; 21 % of MOTOR_TPL claims close after the cut-off.
- **Large-loss or reinsurance layer: not the cause.** MOTOR_TPL has no `large_events` in the baseline; `ultimate_gross` and the pattern are both gross.
- **Case-reserve bias rows (+15 % from 2022): not the cause.** They act on case reserves only; payments and ultimates do not read them. They move `incurred_share` of 2022 onwards, not the 2016 paid share.

## Decision
`development_pattern.csv` gains two columns on the basis of `ultimates.csv`: `paid_share_nominal` and `incurred_share_nominal` (TRY at the spot rate of the payment day, case reserves at the valuation day, ultimate = all payments ever made). The inflation-free columns keep their names and values. One minus `paid_share_nominal` at the cut-off year end equals the unpaid share of `ultimates.csv` (lines in one currency; the other lines add the conversion).

## Consequences
- Check after the change on `baseline medium` (run once, 2026-11-10): MOTOR_TPL unpaid share at the cut-off, `ultimates.csv` against 1 − `paid_share_nominal`, equal to six decimals for all ten accident years (2016: 0.280921 both; 2025: 0.886668 both). Inflation-free for comparison: 0.018834 and 0.787243. The ground-truth comparison of MT12–MT14 on MOTOR_TPL was NOT run.
- Nominal incurred is below the nominal ultimate at every age (2016 at ten years: 0.927; inflation-free 1.001): case reserves are at the prices of their day and are not inflated to the payment day. Inflation-free incurred stays near 1.
- Which basis a method is judged on (MT14's true tail was taken from the inflation-free pattern, 0285: 1.0192; on the nominal basis it is 1/0.719 = 1.39) is for the ground-truth items; this record changes no method.
- `development_pattern.csv` of every scenario gains two columns, so its hashes move (0376).
