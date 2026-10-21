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
- Phase: 1 started · Last gate passed: G0 (2026-10-21) · Last checkpoint: C1 (2026-10-21, PASS on measurable criteria; owner report test not checked) · Last item: P05 (recognition), branch `s/P05-recognition`, based on `s/C1-checkpoint` (not yet merged into `main`)
- Works (run 2026-10-21): `just check` green (338 fast tests; 10.9–13.6 s of tests early in the session, 24–26 s later on the same code with the machine slower: the C1 code measured 23.6 s at that time, so P05 adds about 1–2 s; close to the 30 s limit when the machine is slow); `just test-all` 358 green in 17–21 s. `canary run examples/baseline` writes `out/dd861c707051e569/` (run id changed with P05: AL01/AL02 and the mappings are now determinants, record 0029). `canary run examples/messy_headers` asks once about 7 sheets (six files, market on two), saves 7 profiles in `profiles/`, and the second run asks nothing (run interactively with piped answers and in tests). Baseline medium end to end: 12.4 s with a cold cache (all six files are now read; P04 read two, 2.6 s), 2.1 s warm, of which about 1.2 s is imports
- Path: io (header row found by content, two-pass calamine read, parquet cache by SHA-256, record 0025) → recognition (header, concept scores, column layers canonical/dictionary/fuzzy/values with value-profile checks, personal data dropped, AL02 labels, saved profiles or terminal confirmation; records 0026–0028) → canonical (text dates per column, record 0027; DV row rules as findings) → convert → structures (MT01) → modules.reserving (MT02) → report → manifest (mapping per sheet, sheets not used, `settings.triangles.cut_off_used` next to `cut_off`; records 0023 amended, 0029)
- Verified: messy_headers tiny maps to the same canonical frames as baseline tiny for all six concepts (identical rows kept once; the messy files repeat 1% of rows); header rows equal `truth/layout.csv`; all 64 columns and 6 personal-data columns equal `truth/column_map.csv`; `canary run` on messy tiny writes `triangles.csv`, `factors.csv`, `chain_ladder.csv` byte-identical to the baseline run's; personal-data property test (header and value kinds) never sees a personal column or value in a canonical frame; profiles round-trip; editing a profile changes the run id, reusing it does not; chain ladder, MT01 hand and medium ground-truth tests still pass through the new reader; two baseline runs still give byte-identical manifests and outputs
- Information, no tolerance in a spec: chain ladder ultimate ÷ true ultimate on baseline medium (TRY): GROUP_TERM_LIFE 1.012 incurred / 1.002 paid; MOTOR_OD 0.995 / 0.993; MOTOR_TPL 1.404 / 1.123; PROPERTY 0.982 / 0.908 (from P04; TPL is long-tailed and inflation-driven, MT07 is the planned answer)
- Choices to review: slash dates whose values do not decide the order are read day first and the evidence says so (0027); `--yes` never saves a profile and a run without a terminal stops instead of guessing (0028); `profiles/` is git-ignored (0028); phone, e-mail, IBAN and name value profiles drop only columns whose header is not a field alias, 11-digit identity numbers always (0026); personal columns cannot be mapped by the user, even through an edited profile
- Known gaps: UNVERIFIED: the confirmation screen in a real interactive terminal (only piped answers and the test runner); spreadsheets in Excel; byte-identical output on another machine; CI workflow and pre-commit hooks (not run); `check_folder` and runs on `large`; medium/large of the non-baseline scenarios. Not built: input shapes other than one table per sheet (wide extracts, pivoted periods, periodic files; blueprint 6.2), incremental/cumulative detection, the suggestion model (6.3 layer 5), quality profiler, lineage table, assumptions register (who confirmed a profile is not recorded), market conversion (0024). Unmapped labels of fields outside claim_valuations and claims are listed in the manifest only, not as report findings. Cold reads now cover every file in the folder; recognising unused files from the first rows only would cut the 12 s medium cold run. `test_baseline_tiny_runs_and_reproduces` takes 0.69 s alone (first test of its module reads six files into an empty cache); under `-n auto` many tests take 1–3 s from contention
- Spec drift: AL01, AL02 and CV07 are now named by tests; the rest of the C1 list stands (CL02, CL04–CL11, CV08, MT03, MT06–MT09, PR01, PR03, PR05, PR06; 42 data rules)
- Hygiene: new files and commit messages of this branch carry no AI-tool wording and no trailers; synthetic names and random digits only; 18 earlier commits on `main` still carry a co-author trailer (owner to decide)
- Hours: logged elapsed agent time 3 h 29 min (2 h 43 min up to P04, plus C1 4 min and P05 42 min); owner hours: ask the owner
- Notes: the fixture `manifest.yaml` `sha256` of an `.xlsx` is a content hash over the zip parts, not of the file bytes (C1, no change); `just` is in `~/.local/bin` (not on the Git Bash PATH); `spec/` and `synthetic/scenarios/` must be bundled when packaging; the `large` size has no `policies`/`premiums` spreadsheets (0017); the slow ground-truth test skips when `data/synthetic/baseline/medium` is missing; tests share the project `.cache/` for the fixture spreadsheets (cache writes are atomic)

## Next
- Owner: merge `s/C1-checkpoint`, then `s/P05-recognition`; run `canary run examples/messy_headers` in a terminal and try accept, edit (`3=-`, `concept=claims`) and skip; review records 0025–0029 and the amendment to 0023 (the 0023 edit was made at the owner's request, although records are otherwise superseded, not edited); answer the day-first question in 0027
- Then P06 and P07 in parallel

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
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
