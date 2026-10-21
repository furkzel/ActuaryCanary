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
- Phase: 1 started · Last gate passed: G0 (2026-10-21) · Last checkpoint: G0 (2026-10-21) · Last item: P04 (first end-to-end slice), branch `s/P04-thin-slice`
- Works (run 2026-10-21): `just check` green (259 fast tests, 9.4 s of tests); `just test-all` 276 green; `canary run examples/baseline` writes `out/7e09d151cae16fb2/` with `report.html` (4.8 MB, plotly inlined), `triangles.csv`, `factors.csv`, `chain_ladder.csv`, `manifest.json` in about 0.2 s after imports; baseline medium (180,091 valuation rows) end to end in 2.6 s with a cold cache. Report opened and looked at in a headless browser, light and dark
- Path: io (calamine, parquet cache by SHA-256) → canonical (exact canonical names, DV row rules as findings) → convert (reporting currency only) → structures (MT01 paid/incurred triangles by segment and line) → modules.reserving (MT02 on paid and on incurred) → report → manifest; interfaces in record 0022, run id in 0023, open triangle choices in 0024
- Verified: chain ladder equals the hand fixture (paid, incurred; 1e-12) and RAA/GenIns factors, CDFs, ultimates (1e-9); MT01 hand fixture (annual and quarterly) exact; MT01 ground truth on baseline medium, quarterly development: all 880 cells × paid/incurred equal `truth/ibnr_by_valuation.csv` within 1e-12 after the injected faults' known effects, 66 cells not comparable (lowered paid by an unknown amount); two runs on the tiny baseline give byte-identical outputs and manifest
- Information, no tolerance in a spec: chain ladder ultimate ÷ true ultimate on baseline medium (TRY, ten accident years): GROUP_TERM_LIFE 1.012 (incurred) / 1.002 (paid); MOTOR_OD 0.995 / 0.993; MOTOR_TPL 1.404 / 1.123; PROPERTY 0.982 / 0.908. TPL is long-tailed (2016 still developing at 120 months, tail 1.0) and inflation-driven (recent years 1.3–1.6 on incurred); this is the method's calendar-effect assumption failing, not a data defect (MT07 is the planned answer)
- Known gaps: UNVERIFIED: spreadsheets in Excel (only calamine read them); byte-identical output on another machine; `check_folder` on `large`; baseline, messy_headers and reserve_bias_change at large after the fix; medium/large of the non-baseline scenarios against the checker; benchmark published figures; CI workflow and pre-commit hooks (not run). No market conversion yet: foreign and UNKNOWN-currency amounts are listed, not in triangles (0024). No lineage table, assumptions register, quality profiler or value aliases yet. Currency validity is a three-capital-letter check, not an ISO list. Fiscal years other than January only unit-tested on labels. Under `-n auto` several tests (old synthetic ones and the new triangle property tests) take 0.6–1.9 s; alone the new ones are under 0.5 s. The tiny fixture `manifest.yaml` lists a SHA-256 for `claim_valuations.xlsx` (3e17…) that is not the committed file's (928c…); cause not investigated
- Hygiene: no AI-tool wording in new files or commit messages of this branch; 17 earlier commit messages still carry a co-author trailer (see previous handover); history not rewritten
- Notes: `just` is in `~/.local/bin` (not on the Git Bash PATH); `spec/` and `synthetic/scenarios/` must be bundled when packaging (the report template is in the wheel, checked); the `large` size has no `policies`/`premiums` spreadsheets (0017); `data/synthetic/baseline/medium` was regenerated after P02c for the slow ground-truth test (it lacked `money_columns.csv`); the slow test skips when that folder is missing

## Next
- Owner: review and merge `s/P04-thin-slice`; open `out/<run id>/report.html` after `canary run examples/baseline`; review records 0022–0024 (especially 0024: currencies without a rate are left out of the triangles until market conversion exists)
- Then CHECKPOINT C1

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-21 | P04 | reader with parquet cache, canonical feeds, MT01 triangles, MT02 chain ladder, HTML report, manifest, `canary run`; records 0022–0024 | ~27 min (18:33–19:00) | see branch s/P04-thin-slice |
| 2026-10-21 | P02c | truth currency columns and `money_columns.csv`, USD/EUR claim-scale fix, high_inflation and large_loss magnitudes (rate-based large events), record 0007 spec-format renumbered 0020, record 0021 | ~21 min (18:04–18:25) | see branch s/P02c-truth-fixes |
| 2026-10-21 | G0 | checkpoint: FAIL on owner check of raa/genins; medium measurement of five scenarios, record 0019 | ~10 min (08:05–08:15) | see branch s/G0-checkpoint |
| 2026-10-20 | P02b | baseline calibration: TPL premium 5,500 → 9,500, TPL ten-year ratio 1.77 → 1.03, fixtures regenerated, record 0018, record 0017 updated | ~15 min | see branch s/P02b-calibration |
| 2026-10-20 | P02 | seeded generator, 5 scenarios, tiny/medium/large, truth files, data checker, tiny fixtures, records 0015–0017 | ~50 min | see branch s/P02-synthetic |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
