# Handover

Read this file first. It is the only status document. Everything else is code, specifications (`spec/`), decision records (`docs/decisions/`) or the blueprint (`docs/blueprint.md`).

## What this is
ActuaryCanary turns insurance data in any layout into an auditable, early-warning actuarial report on your own computer. Analytics-first actuarial data science platform; see `docs/blueprint.md` sections 1 and 2.

## How to work here
- Setup `just setup` · Check `just check` (format, lint, types, fast tests under 30 s) · All tests `just test-all` · Run `canary run <folder>`
- Specification first: change `spec/` before code. One rule, one spec file. Tests name the spec ID they prove.
- Decisions: one short numbered record per choice in `docs/decisions/`; records are superseded, never edited.
- One branch per work item, `s/<ID>-<slug>`; the owner merges to `main`.
- No per-work-item report files. Detail goes into commit messages; status goes here.

## Map
- `src/actuarycanary/<component>/` — one subpackage per blueprint component: io, recognition, canonical, quality, convert, structures, measures, methods, modules, report, manifest (also project metadata), spec, cli
- `spec/` — specifications, one subfolder per kind: data, conventions, measures, methods, modules, aliases
- `tests/` — mirrors the package; `conftest.py` sets Hypothesis profiles
- `tests/benchmarks/` — frozen reference values (`raa`, `genins`) and `load.py`; `tests/fixtures/hand/` — hand-worked 4×4 fixtures
- `synthetic/scenarios/*.yaml` — synthetic scenario parameters (`baseline.yaml` is the base); code in `src/actuarycanary/synthetic/`
- `docs/` — blueprint, spec/data/, `decisions/` records 0001–0024
- `project.yaml` — project metadata, single source for CLI and report
- `.github/workflows/ci.yml` — `just check` on Ubuntu and Windows

## State
- Phase: 1 started · Last gate passed: G0 (2026-10-21) · Last checkpoint: C1 (2026-10-21, PASS on measurable criteria; owner report test not checked) · Last item: P07 (bases and structures), branch `s/P07-bases`, based on `e957c3f` (merge of P05); P06 runs in parallel and is not part of this branch
- Works (run 2026-10-21): `just check` green: 410 fast tests (338 before P07), 10.4–11.5 s of tests and 12.5 s wall on a quiet machine, 17.6 s and 23.7 s while the machine was busy (the code before P07 measured 30.6 s once in that state, so the limit is close only under load); `just test-all` 445 green in 19 s (the medium baseline was generated into the git-ignored `data/` for the ground-truth tests). `canary run examples/baseline --basis net --currency TRY --value inflation-adjusted` works (1.7 s warm; run id `637af7717127b800`; report headed `NET, INFLATION_ADJUSTED`, prices of 2025-12-31 with CPI_TR). The default run is unchanged except its run id (new settings fields): market data is read only for `--currency` or the adjusted basis (0031)
- Path: io → recognition → canonical (now also market, premiums and policies row rules) → convert (`market`: series as lookup tables; `currency`: CV01 rules and fallbacks; `inflation`: CV02 factors; `rates`: constant development rate; `bases`: gross/ceded/net and nominal/adjusted amounts per claim row) → structures (`triangles`: every MT01 measure on every basis, origin axes accident, report, underwriting, first valuation; `premium`: earned and unearned premium, earned exposure) → modules.reserving (MT02) → report → manifest. Options of `canary run`: `--basis`, `--currency`, `--value`, `--value-date`, `--price-index`, `--origin-axis`
- Verified: hand fixture of three currencies (TRY, USD, EUR by reciprocal) and index points 100/110/132 gives the hand-computed adjusted gross and net triangles, nominal ceded and net, counts and recoveries; net = gross − ceded in every cell (hand fixture, and property tests over random books in the slow tier); cumulative of the incremental triangle equals the cumulative one; results independent of row order; converting and converting back returns the original (all three rules, USD and EUR); PR02 hand fixture (policy written 1 July, endorsement, cancellation: monthly, quarterly, fiscal-year labels, ceded, net, foreign currency, restated) and PR03 (written to date = earned + unearned); earned exposure by hand and by property; P04 and P05 tests pass unchanged; MT01 ground truth on baseline medium still equal after the refactor; inflation-adjusted gross and net triangles of baseline medium (clean claims, USD and EUR included) equal a plain Python loop that restates claim by claim
- Information, no tolerance in a spec: chain ladder ultimate ÷ true ultimate on baseline medium (TRY): GROUP_TERM_LIFE 1.012 incurred / 1.002 paid; MOTOR_OD 0.995 / 0.993; MOTOR_TPL 1.404 / 1.123; PROPERTY 0.982 / 0.908 (from P04; TPL is long-tailed and inflation-driven, MT07 is the planned answer) (not re-measured in P07). Tiny baseline, NET, inflation-adjusted, TRY: 3 TRY claims and 1 claim of unknown currency leave the adjusted triangles because a row of theirs has no currency (0030)
- Choices to review: 0030 (no fallback invented for a missing average rate of a booking month: the claim leaves the adjusted triangles from that row on and is listed), 0031 (conversion off unless `--currency`; flip the default if conversion should happen whenever a market file exists), 0032 (which row rules were built for the premium structures); earlier: slash dates read day first (0027); `--yes` never saves a profile (0028); `profiles/` git-ignored (0028)
- Known gaps: UNVERIFIED: premium structures on baseline medium against any independent figure (only run for speed: 0.47 s earned premium and 0.48 s exposure on 782,623 premium rows); adjusted basis on the other scenarios and on `large`; `canary run` with the new options on medium; the confirmation screen in a real interactive terminal; spreadsheets in Excel; byte-identical output on another machine; CI workflow and pre-commit hooks (not run). Not built: premium, expense and policy data in `canary run` and its manifest (the structures are functions for the measures item), DV-MKT-06 to 08 and the other quality checks (profiler), the ORIGINAL currency view of triangles, FUNCTIONAL currency (equal to reporting, CV01), allocation of treaty-level ceded amounts (CV03: only claim-level ceded fields), DISCOUNTED values, re-inflation to nominal (MT07), input shapes other than one table per sheet, incremental/cumulative detection, the suggestion model, quality profiler, lineage table, assumptions register
- Spec drift: tests now name CV01 to CV05, CL04, PR01 to PR03 and 19 more data rules (42 before, 23 of 56 now unnamed); not named by any test: CL02, CL05–CL11, CV08, MT03, MT06–MT09, PR05, PR06
- Hygiene: new files and commit messages of this branch carry no AI-tool wording and no trailers; synthetic names only; 18 earlier commits on `main` still carry a co-author trailer (owner to decide)
- Hours: logged elapsed agent time about 4 h 0 min (3 h 29 min up to P05, plus P07 about 30 min); owner hours: ask the owner
- Notes: the fixture `manifest.yaml` `sha256` of an `.xlsx` is a content hash over the zip parts, not of the file bytes (C1, no change); `just` is in `~/.local/bin` (not on the Git Bash PATH); `spec/` and `synthetic/scenarios/` must be bundled when packaging; the `large` size has no `policies`/`premiums` spreadsheets (0017); the slow ground-truth tests skip when `data/synthetic/baseline/medium` is missing (`just synth baseline medium`, 82 s); tests share the project `.cache/` for the fixture spreadsheets (cache writes are atomic); P07 tests that run the whole pipeline or build many triangle sets per example are marked slow. Ten slowest fast tests at the end (under `-n auto`, so with contention): 1.35 s `structures/test_mt01_triangles::test_property_row_order_does_not_matter` (P04), 1.13 s and 0.93 s two `synthetic/test_scenarios` tests, 1.04 s `test_pipeline::test_baseline_tiny_runs_and_reproduces`, 1.00 s `test_pipeline::test_manifest_records_the_cut_off_used_next_to_the_setting`, 0.94 s `cli/test_cli::test_run_writes_report_and_manifest`, 0.88 s `recognition/test_messy` setup, 0.84 s `recognition/test_personal`, 0.83 s `cli/test_cli::test_new_layouts_without_answers_or_yes_stop_with_a_message`; none is a P07 test (the slowest P07 fast tests alone: 0.17 s and 0.10 s, two property tests of the premium structures)

## Next
- Owner: merge `s/P07-bases` (and P06 when done); decide 0031 (conversion default) and 0030 (missing average rate: invent no fallback, or name one in CV01); run `canary run examples/baseline --currency TRY --value inflation-adjusted` and read the report
- Then the measures item (premium structures, claim triangles on every basis are ready to be read) and MT07 (inflation-adjusted chain ladder with a stated future inflation)

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-21 | P07 | market series and CV01 rate rules, CV02 restatement, gross/ceded/net and nominal/adjusted triangles for every MT01 measure, origin axes incl. underwriting, earned/unearned premium and earned exposure, row rules for market/premiums/policies, `canary run --basis --currency --value --origin-axis`; records 0030–0032 | ~30 min (20:53–21:24) | see branch s/P07-bases |
| 2026-10-21 | P05 | header rows by content, concept scores, column layers (dictionary, fuzzy, value profile), personal data dropped, AL02 labels, mapping profiles, terminal confirmation and `--yes`; cut-off used and mappings in manifest, mappings in run id; records 0025–0029, 0023 amended | ~42 min (19:23–20:05) | see branch s/P05-recognition |
| 2026-10-21 | C1 | checkpoint: PASS on run, reproducibility and chain ladder tests; owner report test NOT CHECKED; manifest hash mismatch explained (content hash over zip parts); hours re-estimate | ~4 min (19:07–19:10) | see branch s/C1-checkpoint |
| 2026-10-21 | P04 | reader with parquet cache, canonical feeds, MT01 triangles, MT02 chain ladder, HTML report, manifest, `canary run`; records 0022–0024 | ~27 min (18:33–19:00) | see branch s/P04-thin-slice |
| 2026-10-21 | P02c | truth currency columns and `money_columns.csv`, USD/EUR claim-scale fix, high_inflation and large_loss magnitudes (rate-based large events), record 0007 spec-format renumbered 0020, record 0021 | ~21 min (18:04–18:25) | see branch s/P02c-truth-fixes |
| 2026-10-21 | G0 | checkpoint: FAIL on owner check of raa/genins; medium measurement of five scenarios, record 0019 | ~10 min (08:05–08:15) | see branch s/G0-checkpoint |
| 2026-10-20 | P02b | baseline calibration: TPL premium 5,500 → 9,500, TPL ten-year ratio 1.77 → 1.03, fixtures regenerated, record 0018, record 0017 updated | ~15 min | see branch s/P02b-calibration |
| 2026-10-20 | P02 | seeded generator, 5 scenarios, tiny/medium/large, truth files, data checker, tiny fixtures, records 0015–0017 | ~50 min | see branch s/P02-synthetic |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
