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
- `synthetic/` — synthetic data truth parameters and (later) generator
- `docs/` — blueprint, spec/data/, `decisions/` records 0001–0007
- `project.yaml` — project metadata, single source for CLI and report
- `.github/workflows/ci.yml` — `just check` on Ubuntu and Windows

## State
- Phase: 0 · Last gate passed: none · Last checkpoint: none
- Works: `just check` green locally on Windows (PowerShell; 199 fast tests, ~7 s) and `just test-all` (215 tests, ~14 s); `canary info`, `canary --version`; `just spec-index` lists 64 reviewed specs; benchmarks `raa`, `genins` and hand fixtures loadable
- Works (P02, mode A): `just synth <scenario> <size>` writes the six spreadsheets, `canonical/*.parquet` and `truth/*.csv` for `baseline`, `messy_headers`, `high_inflation`, `large_loss`, `reserve_bias_change` at `tiny`, `medium`, `large`; `just synth-fixtures` refreshes `tests/fixtures/synthetic/` and `examples/` (baseline and messy_headers, tiny). Ran: all five at tiny (read back through `synthetic/check.py`, the violations are exactly the injected faults); baseline medium (180k valuation rows, 50 s, parameters recovered within 4 sigma in the slow tests); baseline large (994,821 valuation rows, 62 s; claim_valuations read back equal to the parquet)
- Known gaps: UNVERIFIED: the spreadsheets opened in Excel (only calamine read them); byte-identical output on another machine or CPU (the same machine twice is tested; the slow test of the committed fixtures can fail elsewhere); `check_folder` on `large`; medium and large of the four scenarios other than baseline. Benchmark published figures UNVERIFIED; hand fixtures not yet checked by owner; no actuarial logic; CI workflow and pre-commit hooks UNVERIFIED (not run); no LICENSE (see 0006); `just` was installed with `uv tool install rust-just` (`~/.local/bin`)
- Notes: the Map entry for `synthetic/` is stale (now `scenarios/*.yaml`; code in `src/actuarycanary/synthetic/`) and the Open decisions section is left for the owner; `spec/` and `synthetic/scenarios/` must be bundled when packaging; baseline parameters changed from the first sheet (record 0016); the `large` size has no spreadsheet for `policies` and `premiums` (record 0017)

## Next
- Owner: review and merge `s/P02-synthetic`; decide the title-rows conflict (CV07 says the header is in the first non-empty row, `messy_headers` writes 1 to 3 title rows above it; record 0017); check that the baseline loss ratios look right to an actuary (record 0016; at large the ten-year ultimate loss ratios are own damage 79%, third-party liability 177%, property 88%, group life 56%)
- Owner action still open: check the hand fixtures in a spreadsheet; mark `checked_by_owner: true` in each `expected.yaml` (`tests/fixtures/hand/`, `tests/benchmarks/raa/`, `tests/benchmarks/genins/`)
- Then the next work item. Readers and the recogniser can start from `examples/baseline`, `examples/messy_headers` and the matching `truth/` in `tests/fixtures/synthetic/`

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-20 | P02 | seeded generator, 5 scenarios, tiny/medium/large, truth files, data checker, tiny fixtures, records 0015–0017 | ~50 min | see branch s/P02-synthetic |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
