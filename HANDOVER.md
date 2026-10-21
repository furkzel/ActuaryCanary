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
- Phase: 0 complete · Last gate passed: G0 (2026-10-21) · Last checkpoint: G0 (2026-10-21) · After G0: P02c (truth currency, scenario magnitudes, record numbering)
- Works (run 2026-10-21, after P02c): `just check` green (205 fast tests); `just test-all` 221 tests green; 64 specs, all `reviewed`; `just synth <scenario> <size>` for all five scenarios at medium (50–70 s each) and `high_inflation`, `large_loss` at large (94 s); `canary info`, `canary --version`; benchmarks `raa`, `genins` and hand fixtures loadable
- Medium measurement (record 0021, TRY rows, ten-year ultimate gross ÷ earned premium; OD / TPL / PROPERTY / life): baseline 0.808 / 0.957 / 0.796 / 0.595; high_inflation 1.068 / 1.387 / 1.130 / 0.596 (targets 0.90–1.30 / 1.20–2.00 / 0.90–1.30); large_loss 0.808 / 1.205 / 1.083 / 0.595 (targets TPL 1.10–1.50, PROPERTY 1.00–1.60). Large, same two: high_inflation 1.034 / 1.601 / 1.171; large_loss 0.785 / 1.202 / 1.126. Baseline medium output unchanged by the scenario work. Truth files now declare the currency of every money column (`truth/money_columns.csv`); the USD/EUR claim scale was wrong (double division by the starting rate) and is fixed
- Known gaps: UNVERIFIED: spreadsheets in Excel (only calamine read them); byte-identical output on another machine; `check_folder` on `large`; baseline, messy_headers and reserve_bias_change at large after the fix; medium/large of the non-baseline scenarios against the checker; benchmark published figures; CI workflow and pre-commit hooks (not run). `large_loss` at tiny has too few large events for its ratio to be comparable (record 0021). TPL premium pass-through in `high_inflation` is one level, not a time path. No actuarial logic yet. No LICENSE (0006). Measure and method tests do not exist yet by plan: 37 of 64 spec IDs have no test naming them (information only); no code rule without a spec found
- Hygiene: no AI-tool wording as a whole word in any of the 254 tracked files or file names; no personal-data-like values (`personal_data_columns.csv` is header only). BUT 17 earlier commit messages carry a co-author trailer that names the tool used, so the history does mention it; decide whether to rewrite history before the repository is published. Largest tracked file 299 KB.
- Notes: `just` is in `~/.local/bin` (not on the Git Bash PATH); `spec/` and `synthetic/scenarios/` must be bundled when packaging; the `large` size has no `policies`/`premiums` spreadsheets (0017)

## Next
- Owner: set `checked_by_owner: true` in `tests/benchmarks/raa/expected.yaml` and `tests/benchmarks/genins/expected.yaml` after checking them (hand fixtures already true in the working tree; commit it); then G0 passes without re-running anything
- Owner: merge `s/G0-checkpoint`, then `s/P02c-truth-fixes` (it is based on `s/G0-checkpoint`, not on `main`, because record 0019 and the G0 handover live there); review record 0021 (foreign-claim fix, the two scenarios' parameters, renumbered record 0020-specification-format, trailers in history)
- Then P04 (first reader/recogniser item in the plan), starting from `examples/baseline`, `examples/messy_headers` and the matching `truth/` in `tests/fixtures/synthetic/`; read `truth/money_columns.csv` before using any amount
- Hours: the log sums to about 2.2 h up to this item; the plan's ranges are not in the repository, so no re-estimate is made here

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-21 | P02c | truth currency columns and `money_columns.csv`, USD/EUR claim-scale fix, high_inflation and large_loss magnitudes (rate-based large events), record 0007 spec-format renumbered 0020, record 0021 | ~21 min (18:04–18:25) | see branch s/P02c-truth-fixes |
| 2026-10-21 | G0 | checkpoint: FAIL on owner check of raa/genins; medium measurement of five scenarios, record 0019 | ~10 min (08:05–08:15) | see branch s/G0-checkpoint |
| 2026-10-20 | P02b | baseline calibration: TPL premium 5,500 → 9,500, TPL ten-year ratio 1.77 → 1.03, fixtures regenerated, record 0018, record 0017 updated | ~15 min | see branch s/P02b-calibration |
| 2026-10-20 | P02 | seeded generator, 5 scenarios, tiny/medium/large, truth files, data checker, tiny fixtures, records 0015–0017 | ~50 min | see branch s/P02-synthetic |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
