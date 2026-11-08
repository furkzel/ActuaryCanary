# 0363 — The fast suite on the CI runner: 37 s, and what was moved out of it

## Context
The fast suite (`just check`, `pytest -m "not slow"`) must run in under 30 s (HANDOVER, "How to work here"). It was 66 s on the owner's laptop and about 26 s on the Ubuntu runner before P27.

**Read with `gh run list` and `gh run view` (gh 2.81.0 is available), 2026-11-08:** the newest run of `ci` on `main` is 42505927290 (the merge of P27, pushed 17:37 UTC). Ubuntu: `just check` 71 s in all; pytest "1698 passed in 37.08s" (started 17:38:43, the first dots at 17:39:00, the end at 17:39:21). Windows: "1698 passed in 28.40s", `just check` 65 s. **The runner is above 30 s.**

Where the 37 s go, from the profile of the collection and the slowest-durations list on the laptop: about 17 s before the first test runs (each worker imports and collects the whole suite, 1,883 tests of which 1,700 are fast; the specifications were loaded ten times per worker, 0362), and the first use of the session fixtures `default_run` and `cli_run`, 4 to 8 s on each worker. The tests themselves are short: about 45 of the fast tests take 0.5 s or more, and the marker description of the repository says such a test is `slow`.

## Decision
- The specifications are loaded once per process (0362): collection 14.2 -> 11.5 s on the laptop.
- 21 fast tests are marked `slow` (they run with `just test-all`), all of them tests of the synthetic generator, its layout scenario or the recognition of that layout (the recognition of the messy layout keeps its other tests in the fast suite); every one takes 0.5 to 1.3 s, together about 19 s of worker time (the sum of their measured durations):
  - `tests/synthetic/test_files.py`: the `messy_headers` copy of every test of the module (the fixture parameter carries the mark; 12 tests: the six spreadsheets, identifiers as text, dates as dates, the market sheets, reading through the truth for six feeds, the manifest hashes, the examples equal the fixtures). The `baseline` copy stays fast.
  - `tests/synthetic/test_scenarios.py`: `test_high_inflation_raises_the_price_level_and_the_nominal_cost_of_the_same_claims` (1.25 s), `test_reserve_strengthening_shows_in_incurred_not_in_paid_development` (1.23 s), `test_fixed_large_claims_land_on_the_chosen_days` (1.05 s).
  - `tests/synthetic/test_determinism.py`: `test_the_market_does_not_depend_on_the_portfolio_size` (0.91 s), `test_the_same_seed_gives_the_same_tables_and_truth` (0.75 s); the slow suite also has the byte-level determinism test of every file.
  - `tests/synthetic/test_portfolio.py`: `test_policy_counts_scale_with_the_portfolio_scale` (0.86 s).
  - `tests/recognition/test_messy.py`: `test_messy_maps_to_the_same_canonical_frames_as_baseline` (0.91 s and a 0.68 s fixture).
  - `tests/docs/test_docs.py`: `test_an_example_has_its_six_files_and_a_report_that_matches_its_manifest` for the examples `demo` (1.28 s) and `messy_headers` (1.22 s); `baseline` stays fast.
- The command-line tests (`cli_run`) stay fast: they are the only end-to-end test of the command in the fast suite.
- `just test` and `just check` print the fifteen slowest tests (`--durations=15`), so the next CI log shows what to move.

## Result (this machine, six workers)
This laptop's timing varies by 10 s or more from run to run (the same tree: 37.4 to 54.7 s), so the figures below come from alternating the original tree and the changed one:

| tree | runs (s) | mean |
| --- | --- | --- |
| original (1,698 fast tests) | 65.0, 54.6 | 59.8 |
| specification cache and 19 tests moved (1,725 fast tests) | 49.1, 44.6 | 46.9 |
| final: 21 tests moved (1,723 fast tests; not alternated) | 52.3, 37.4 | 44.9 |

The number of fast tests is 25 more than before: the 41 tests added by this item and the 5 the documentation tests make for the five new records, minus the 21 moved. The laptop's gain is a factor of about 0.75 to 0.78; on the same factor the runner would need 28 to 29 s from its 37.08 s. **That is under 30 s by a thin margin and UNVERIFIED until the pull request has run on Ubuntu.** If it is still above, the next candidates are the first-use cost of `default_run` and `cli_run` on each worker (a mark on their users does not help: about 170 tests share `default_run`; `cli_run` has four users), and the 0.5 to 1.1 s tests of `tests/report`, `tests/modules`, `tests/methods/severity` and `tests/measures` that are now at the top of the `--durations=15` list printed by `just check`.
