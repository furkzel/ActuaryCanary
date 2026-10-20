# 0005 — Branch per work item, owner merges, one status file

## Context
Work is done in short, separate items, often by different sessions, and each session starts without memory.

## Decision
- One branch per work item, named `s/<ID>-<slug>`; small commits; the branch is pushed, never `main`.
- The owner reviews and merges.
- `HANDOVER.md` is the only status file: map, state, next steps, open decisions and a log of the last 15 items. No per-item report files; detail goes into commit messages.

## Consequences
- Anyone can resume from `HANDOVER.md` alone.
- `main` only moves through reviewed merges.
