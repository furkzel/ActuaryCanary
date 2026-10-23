# 0110 — `canary demo` runs on `examples/demo` only

## Context
Record 0091 let `canary demo` fall back to `examples/baseline` until the demo example existed, and 0090 bundled `examples/baseline`. The demo example now exists (0102).

## Decision
- `canary demo` looks for `examples/demo` and nothing else; with no such folder next to the program it stops with a message (the fallback of 0091 is removed).
- The program bundle holds the six workbooks of `examples/demo` (not its `report/` folder, not the other examples); `packaging/canary.spec` stops the build when they are missing.
- The release smoke test and `packaging/compare_manifests.py` compare the built `canary demo` with `canary run examples/demo --yes` from source: the same run id and the same SHA-256 on every output (names and hashes), as well as inputs, specs and settings.
- The documentation check reads README and the guide: every `canary` command named in a code block or code span must exist in the CLI, and so must every `--option` they mention.

## Consequences
- The run id of the demo is `86413bc4799ade00` (record 0102); it changes only when a result legitimately changes, and `just examples` then rewrites the example reports.
- A new command or option of the CLI that the documents mention must exist before the test passes; a removed one breaks the documents' test.
