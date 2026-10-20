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
- `docs/` — blueprint, input set v1, `decisions/` records 0001–0007
- `project.yaml` — project metadata, single source for CLI and report
- `.github/workflows/ci.yml` — `just check` on Ubuntu and Windows

## State
- Phase: 0 · Last gate passed: none · Last checkpoint: none
- Works: `just check` green locally on Windows (PowerShell and bash; 15 tests, ~5 s); `canary info`, `canary --version`; benchmarks `raa`, `genins` and hand fixtures loadable (`tests/benchmarks/load.py`; `just check` 22 tests)
- Known gaps: benchmark values are from the reference implementation, published figures UNVERIFIED; hand fixtures not yet checked by owner; no actuarial logic; CI workflow and pre-commit hooks UNVERIFIED (not run); no LICENSE (licence undecided, see 0006); `just` was installed locally with `uv tool install rust-just`

## Next
- P01 (P03 done)
- Owner action: check the hand fixtures in a spreadsheet; mark `checked_by_owner: true` in each `expected.yaml` (`tests/fixtures/hand/`, `tests/benchmarks/raa/`, `tests/benchmarks/genins/`)
- Works: `just check` green locally on Windows (PowerShell; 48 tests, ~5 s); `canary info`, `canary --version`; `just spec-index` lists 64 specs (6 data concepts, 8 conventions, 30 measures, 10 methods, 6 modules, 2 alias dictionaries), all draft 0.1.0; the loader validates every file and cross-reference
- Known gaps: no actuarial logic; specs not yet reviewed by the owner; the test files named in the measure specs do not exist yet; CI workflow and pre-commit hooks UNVERIFIED (not run); no LICENSE (licence undecided, see 0006); `just` was installed locally with `uv tool install rust-just`; the Map and Open decisions sections are stale (input set now in `spec/data/`; large-loss threshold decided in 0010) and left for the owner; `spec/` must be bundled when packaging

## Next
- Owner review of specs (status draft → reviewed, version 1.0.0), then P02
- P03 if not done yet (parallel with P01)

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Large-loss threshold rule; health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
