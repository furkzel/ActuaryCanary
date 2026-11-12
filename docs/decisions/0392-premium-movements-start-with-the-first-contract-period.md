# 0392 — Premium movements start with the first contract period (DV-RTR-06)

## Context
The platform's rule DV-RTR-06 (premium half: a premium movement is booked no earlier than the treaty's `inception_date`) warned in every generated scenario that has treaties (54 rows on the tiny baseline, records 0384 and 0390). The generator's own checker implemented the claim half only.

## Cause
A treaty renews every year on its inception date (2016-01-01 in the scenarios). The treaty table lists the contract periods that end after the first day of the simulated years, so at tiny size the first listed period starts on 2022-01-01. The ceded rows of the premiums feed, from which the premium movements are summed (DV-RTR-11), were cut at the treaty's own inception (2016), so the policies of the year before the simulated years (their premium booked in 2021) were ceded to a treaty period that the table does not list: the movements began one year before the first listed treaty period.

## Decision
- A treaty cedes premium from the start of the first contract period it lists, that is the first annual period from its inception that ends after the first day of the simulated years (`days.first_contract_start`, used by `portfolio.build_premiums` for quota-share, excess-of-loss rate and surplus treaties; `build.simulate` passes the first day). The cut is made where the ceded rows are made, so the premiums feed and the movements stay equal (DV-RTR-11). Nothing else in the movements changes.
- The generator's checker (`check_phase2.py`) now implements the premium half: a CEDED_PREMIUM or REINSTATEMENT_PREMIUM booked before the first inception date of its treaty counts under DV-RTR-06, as the platform's rule does.
- `tests/quality/test_scenario_faults.py` no longer excludes DV-RTR-06 and asserts that it does not fire on the baseline and reinsurance_heavy scenarios; the failing case of the rule stays tested on tables built in code (`tests/quality/test_checks_feeds.py`). `tests/synthetic/test_phase2_reinsurance.py` asserts that no premium or commission movement precedes its treaty's first listed period. The quota-share test of `test_portfolio.py` had assumed the ceded share of all gross premium since 2016; its premise changed and it now takes the gross from the first ceding day.

## Truth files
The ceded premium, reinsurance and reconciliation truth files are cut at the first day of the simulated years (`window_start`) and did not contain the removed rows; none of them moved (checked by hash, below).

## Files that moved (tiny, all scenarios that have treaties; record 0391 is the reference)
`canonical/premiums.parquet`, `canonical/reinsurance_transactions.parquet`, `premiums.xlsx`, `reinsurance_transactions.xlsx`, `manifest.yaml` (digests and row counts), `truth/layout.csv`, `truth/layout_phase2.csv` (row counts); in `messy_headers` and `messy_incremental` also `truth/anomalies.csv`, `truth/injected_faults.csv`, `truth/value_map.csv`, `truth/value_map_phase2.csv`, because their faults and value maps are placed on the rows of the premium file, of which some are gone. The pinned digests in `tests/synthetic/tiny_sha256_f1a.yaml` (slow test) are renewed at the end of stage 2.

## Consequences
Premiums feeds of every scenario with treaties lose the ceded rows booked before the first listed period. The committed `examples/` and `tests/fixtures/synthetic/` are older than the generator until Gate v1.3.
