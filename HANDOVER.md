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
- `synthetic/` — synthetic data truth parameters and (later) generator
- `docs/` — blueprint, input set v1, `decisions/` records 0001–0006
- `project.yaml` — project metadata, single source for CLI and report
- `.github/workflows/ci.yml` — `just check` on Ubuntu and Windows

## State
- Phase: 0 · Last gate passed: none · Last checkpoint: none
- Works: `just check` green locally on Windows (PowerShell and bash; 15 tests, ~5 s); `canary info`, `canary --version`
- Known gaps: no actuarial logic; CI workflow and pre-commit hooks UNVERIFIED (not run); no LICENSE (licence undecided, see 0006); `just` was installed locally with `uv tool install rust-just`

## Next
- P01 and P03 (can run in parallel)

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Large-loss threshold rule; health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~40 min | see branch s/P00-skeleton |
