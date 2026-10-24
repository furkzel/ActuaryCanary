# 0200 — Planned specifications stay out of every run

## Context
P20 writes the phase 2 specifications as drafts before any of them is built. The code reads every data concept, module and method in `spec/` on each run: quality coverage lists every concept, the module runner runs every module, recognition matches columns against every concept, and the report lists every method. The versions of AL01, AL02 and CV03 enter the run id. Drafts dropped into `spec/` as they are would change the version 1.0 report, the golden copy, the examples and the run ids in the guide. The item may change only CV03 and the alias dictionaries among existing specs, and P21 regenerates goldens in parallel.

## Decision
Chosen by the owner on 2026-10-23 (flag and separate files):
- `SpecBase.implemented` (default true). `load_specs()` validates every file and checks references on all specs and again on the built ones, then returns the built specs. `load_specs(planned=True)` returns all of them, for the index and the tests. A built spec can never use a planned one.
- New planned files carry `implemented: false` and `status: draft`. The item that builds a spec sets `implemented: true` in the same change.
- Aliases of planned concepts go into `columns-planned.yaml` (AL03) and `values-planned.yaml` (AL04). They are optional files, checked together with AL01 and AL02. The building item moves the entries into AL01 and AL02 with a new version.
- Treaty-level ceded allocation is CV09, the planned amendment of CV03. CV03 1.0.0 stays as it is until the reinsurance item folds CV09 into CV03 1.1.0.
- New optional fields for the drafts: `requires_decision` on every spec, `champion` on methods (tier C must name a tier A or B method), and `blocking_rules`, `outputs` and `report_page` on modules. The value basis DISCOUNTED and the dimensions of the new measures are also allowed. Existing files do not use them, so nothing they mean changes.
- `just spec-index` lists planned specs with a Built column.

## Consequences
- AL01, AL02, CV03 and every existing spec are unchanged, so run ids, the golden copy and the examples do not move. The fast and full suites run as before.
- Work item 2's "amend CV03 with a new version" and work item 1's alias changes are deferred to the building items, by the owner's choice.
- A building item has three steps: flip the flag, move the aliases, update the version-1 scope test in `tests/spec/test_specs.py`.
