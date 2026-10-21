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
- Phase: 1 started · Last gate passed: G0 (2026-10-21) · Last checkpoint: C1 (2026-10-21) · Last item: P04 merged into `main`
- C1 result: PASS on the three measurable criteria (`run` makes a report and manifest; two runs of `canary run examples/baseline` into different folders give identical SHA-256 for all five files including `report.html`; hand fixture and RAA/GenIns chain ladder tests pass). Owner test of the first report: NOT CHECKED (no owner notes yet)
- Works (run 2026-10-21): `just check` green (259 fast tests, 10.0 s of tests, 20 s in all); `just test-all` 276 green in 19 s (21 s with durations). The five slowest are setup of the slow synthetic fixtures (about 7.5 s each, marked slow). `canary run examples/baseline` writes `out/7e09d151cae16fb2/` (`report.html` 4.8 MB with plotly inlined, `triangles.csv`, `factors.csv`, `chain_ladder.csv`, `manifest.json`); baseline medium (180,091 valuation rows) end to end in 2.6 s with a cold cache
- Path: io (calamine, parquet cache by SHA-256) → canonical (exact canonical names, DV row rules as findings) → convert (reporting currency only) → structures (MT01 triangles by segment and line) → modules.reserving (MT02 on paid and incurred) → report → manifest; interfaces in record 0022, run id in 0023, open triangle choices in 0024
- Verified: chain ladder equals the hand fixture (1e-12) and RAA/GenIns factors, CDFs, ultimates (1e-9); MT01 hand fixture exact; MT01 ground truth on baseline medium (quarterly): 880 cells × paid/incurred equal the truth within 1e-12 after known fault effects, 66 cells not comparable; reproducible outputs (above)
- Information, no tolerance in a spec: chain ladder ultimate ÷ true ultimate on baseline medium (TRY): GROUP_TERM_LIFE 1.012 incurred / 1.002 paid; MOTOR_OD 0.995 / 0.993; MOTOR_TPL 1.404 / 1.123; PROPERTY 0.982 / 0.908. TPL is long-tailed and inflation-driven; the calendar-effect assumption fails, not a data defect (MT07 is the planned answer)
- Fixture manifest hash (resolved): `sha256` in the synthetic `manifest.yaml` is not the SHA-256 of the file bytes for `.xlsx`. `synthetic/writer.py:sha256` hashes the sorted part names and uncompressed parts of the zip archive (independent of the compression library); parquet and csv are hashed as bytes. Checked: all 12 spreadsheet, parquet and 14 truth entries of `tests/fixtures/synthetic/baseline` match that function; only the six `.xlsx` differ from `sha256sum`. Git is not involved (`.gitattributes` marks `*.xlsx` binary; `git ls-files --eol` shows `-text`; stored bytes equal the working file). No change needed. Only caution: the reader cache (`file_sha256`) and the run manifest hash raw bytes, so the two meanings differ; a one-line comment in `manifest.yaml` writer or a key name `sha256_content` would remove the confusion (not done, product code)
- Spec drift (list): of 52 spec IDs with a file prefix (measures, methods, conventions, aliases) 21 are named by no test: AL01, AL02, CL02, CL04–CL11, CV08, MT03, MT06–MT09, PR01, PR03, PR05, PR06. AL01, AL02 and MT03 are named only in docstrings of code that does not implement them. No test names an unknown ID (CL99 and PR99 are deliberate negative cases). Of 56 data rules (DV-xxx-nn) 42 are named by no test, including DV-CLV-08 to 14 and all of EXP, MKT, POL, PRM except -02; DV-MKT-07 and -08 have no code reference. No code implements a rule absent from the specs (found by ID only; behaviour not audited)
- Known gaps: UNVERIFIED: spreadsheets in Excel (only calamine read them); byte-identical output on another machine; `check_folder` on `large`; baseline, messy_headers and reserve_bias_change at large after the fix; medium/large of the non-baseline scenarios against the checker; benchmark published figures; CI workflow and pre-commit hooks (not run). No market conversion yet (0024). No lineage table, assumptions register, quality profiler or value aliases yet. Currency validity is a three-capital-letter check. Fiscal years other than January only unit-tested on labels. Under `-n auto` some tests take 0.6–1.9 s
- Hygiene: search of tracked text files for AI-tool, assistant, model and prompt wording: no hits except this paragraph; no `.[name]` or similar files tracked; no personal-data-like values (no emails, long digit runs, IBANs). 18 commits on `main` (P00–P03, P02b, G0 checkpoint) carry a co-author trailer; later commits do not; history not rewritten, owner to decide. Largest tracked files are the spreadsheets (at most 292 KB); `.git` 4.8 MB; `out/`, `data/`, `.cache/` ignored
- Hours: logged elapsed agent time 2 h 43 min (5+31+4+50+15+10+21+27 min) against the plan's 20–31 h to the first prototype, counting agent and owner work. Owner review time is not in the log; owner hours so far: ask the owner. Re-estimate of agent time remaining (P05–P12, G2, G3): 5–12 h (8 items at 25–75 min, G2 and G3 about 1 h each), uncalibrated; items with Excel, packaging and large runs are the upper end
- Notes: `just` is in `~/.local/bin` (not on the Git Bash PATH); `spec/` and `synthetic/scenarios/` must be bundled when packaging (the report template is in the wheel, checked); the `large` size has no `policies`/`premiums` spreadsheets (0017); `data/synthetic/baseline/medium` was regenerated after P02c for the slow ground-truth test; the slow test skips when that folder is missing

## Next
- Owner: open `out/<run id>/report.html` after `canary run examples/baseline` and write notes here (the C1 owner test); review records 0022–0024; give a rough figure of owner hours so far; decide on the 18 trailer commits
- Then P05

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
| 2026-10-21 | C1 | checkpoint: PASS on run, reproducibility and chain ladder tests; owner report test NOT CHECKED; manifest hash mismatch explained (content hash over zip parts); hours re-estimate | ~4 min (19:07–19:10) | see branch s/C1-checkpoint |
| 2026-10-21 | P04 | reader with parquet cache, canonical feeds, MT01 triangles, MT02 chain ladder, HTML report, manifest, `canary run`; records 0022–0024 | ~27 min (18:33–19:00) | see branch s/P04-thin-slice |
| 2026-10-21 | P02c | truth currency columns and `money_columns.csv`, USD/EUR claim-scale fix, high_inflation and large_loss magnitudes (rate-based large events), record 0007 spec-format renumbered 0020, record 0021 | ~21 min (18:04–18:25) | see branch s/P02c-truth-fixes |
| 2026-10-21 | G0 | checkpoint: FAIL on owner check of raa/genins; medium measurement of five scenarios, record 0019 | ~10 min (08:05–08:15) | see branch s/G0-checkpoint |
| 2026-10-20 | P02b | baseline calibration: TPL premium 5,500 → 9,500, TPL ten-year ratio 1.77 → 1.03, fixtures regenerated, record 0018, record 0017 updated | ~15 min | see branch s/P02b-calibration |
| 2026-10-20 | P02 | seeded generator, 5 scenarios, tiny/medium/large, truth files, data checker, tiny fixtures, records 0015–0017 | ~50 min | see branch s/P02-synthetic |
| 2026-10-20 | P03 | benchmarks raa/genins, hand fixtures, loader, record 0007 | ~4 min | see branch s/P03-benchmarks |
| 2026-10-20 | P01 | 64 draft specs, loader and reference checks, spec index, records 0007–0014 | ~31 min | see branch s/P01-specs |
| 2026-10-20 | P00 | skeleton, toolchain, tiers, records 0001–0006 | ~5 min | see branch s/P00-skeleton |
