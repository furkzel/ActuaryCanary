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
- `docs/` — blueprint, spec/data/, `decisions/` records 0001–0019
- `project.yaml` — project metadata, single source for CLI and report
- `.github/workflows/ci.yml` — `just check` on Ubuntu and Windows

## State
- Phase: 0 · Last gate passed: none · Last checkpoint: G0 (2026-10-21), verdict FAIL on one criterion: `checked_by_owner` is still false in `tests/benchmarks/raa/expected.yaml` and `tests/benchmarks/genins/expected.yaml`
- Works (run 2026-10-21): `just check` green (199 fast tests, 6.7 s of tests, 16 s whole); all 215 tests, 15.7 s (`uv run pytest -n auto`); 64 specs, all `reviewed`; `just synth baseline tiny` and `messy_headers tiny` write valid files with truth (the data checker tests pass); all five scenarios generated at medium in 50–61 s each; `canary info`, `canary --version`; benchmarks `raa`, `genins` and hand fixtures loadable
- Medium measurement: baseline is inside every record 0018 target (OD 0.808, TPL 0.957, PROPERTY 0.789, life 0.595; TPL only just above its 0.95 bound); the other four scenarios deviate as designed (record 0019)
- Known gaps: UNVERIFIED: spreadsheets in Excel (only calamine read them); byte-identical output on another machine; `check_folder` on `large`; medium/large of the four non-baseline scenarios against the checker; benchmark published figures; CI workflow and pre-commit hooks (not run). The unit of `earned_premium` in `truth/ultimates.csv` for USD/EUR rows (record 0019). No actuarial logic yet. No LICENSE (0006). Measure and method tests do not exist yet by plan: 37 of 64 spec IDs have no test naming them (information only); tests naming an unknown spec ID: none (CL99/PR99 in `test_loader_errors.py` are deliberate negative cases); no code rule without a spec found
- Hygiene: no AI-tool wording as a whole word in any of the 254 tracked files or file names; no personal-data-like values (`personal_data_columns.csv` is header only). BUT 17 commit messages carry a `Co-Authored-By: [name] …` trailer, so the history does mention an AI tool; decide whether to rewrite history before the repository is published. Largest tracked file 299 KB. Two records are numbered 0007
- Notes: `just` is in `~/.local/bin` (not on the Git Bash PATH); `spec/` and `synthetic/scenarios/` must be bundled when packaging; the `large` size has no `policies`/`premiums` spreadsheets (0017); the working tree had an uncommitted owner edit `checked_by_owner: true` in `tests/fixtures/hand/expected.yaml`, left as is

## Next
- Owner: set `checked_by_owner: true` in `tests/benchmarks/raa/expected.yaml` and `tests/benchmarks/genins/expected.yaml` after checking them (hand fixtures already true in the working tree; commit it); then G0 passes without re-running anything
- Owner: merge `s/G0-checkpoint`; review record 0019 (TPL premium margin at medium, high_inflation and large_loss magnitudes, `earned_premium` unit, trailers in history)
- Then the next work item (first reader/recogniser item in the plan), starting from `examples/baseline`, `examples/messy_headers` and the matching `truth/` in `tests/fixtures/synthetic/`
- Hours: the log sums to about 1.75 h for P00–P02b plus ~10 min for this checkpoint; the plan's ranges are not in the repository, so no re-estimate is made here

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-21 | G0 | checkpoint: FAIL on owner check of raa/genins; medium measurement of five scenarios, record 0019 | ~10 min (08:05–08:15) | see branch s/G0-checkpoint |
| 2026-10-20 | P02b | baseline calibration: TPL premium 5,500 → 9,500, TPL ten-year ratio 1.77 → 1.03, fixtures regenerated, record 0018, record 0017 updated | ~15 min | see branch s/P02b-calibration |
| 2026-10-20 | P02 | seeded generator, 5 scenarios, tiny/medium/large, truth files, data checker, tiny fixtures, records 0015–0017 | ~50 min | see branch s/P02-synthetic |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
