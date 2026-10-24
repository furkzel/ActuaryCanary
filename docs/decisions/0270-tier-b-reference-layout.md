# 0270 — Layout of the tier B references

## Context
Decision 0007 froze reference values for MT02–MT06 as `expected.yaml` files. Tier B (MT11–MT22) needs about twenty more references of four kinds: package output, an external tool (R), scipy output and hand-worked cases. The owner has to be able to open each one in a spreadsheet and check it.

## Decision
- One folder per reference: `tests/benchmarks/tier_b/<id>/` for package, scipy and R output, `tests/fixtures/hand/tier_b/<id>/` for hand-worked cases. The old `raa`, `genins`, `clrd_wkcomp` folders and `tests/fixtures/hand/expected.yaml` are not touched.
- Each folder has `manifest.yaml` (spec IDs, kind, tool and version, calls, how produced, seed, tolerance note, `checked_by_owner: false`), the input CSVs and `values.csv` with the columns quantity, key, value, rel_tol, note. The note column shows the working of a hand number or says "package" or "derived".
- `tests/benchmarks/tier_b/coverage.yaml` records the tier B specs without a reference (none) and what each reference leaves open; a test fails when a tier B spec has neither.
- The scripts that produce the files live in `tests/benchmarks/tools/` and are run by hand. The tests never import chainladder and never run R; they read the files and recompute the numbers from the inputs with numpy and scipy.
- Sampled data (scipy fits) are stored as CSV so no test depends on a random stream.

## Consequences
- The owner sets `checked_by_owner: true` per folder after checking `values.csv`.
- A new reference is a script entry and a folder; the coverage test needs no change unless a spec is added.
