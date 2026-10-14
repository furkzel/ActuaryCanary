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
(filled when the repository skeleton exists)

## State
- Phase: 0 · Last gate passed: none · Last checkpoint: none
- Works: nothing yet
- Known gaps: everything

## Next
- P00 — repository skeleton, toolchain, test tiers, decision records

## Open decisions
- Licence (not decided); author line, contact and repository URL left empty on purpose
- Large-loss threshold rule; health segment in phase 1; timing of method notes (blueprint 18.2)

## Log (newest first, keep the last 15 lines)
| Date | Item | Outcome | Elapsed | Commit |
| --- | --- | --- | --- | --- |
