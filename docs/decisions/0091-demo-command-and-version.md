# 0091 — `canary demo` and the version

## Context
The demo must work from the archive alone, and its result must be the one a run from source gives. `canary --version` must match the release tag.

## Decision
- `canary demo [--out DIR] [--open/--no-open]` runs `canary run <example> --yes` with default settings on the example data found next to the program (`examples/demo`, or `examples/baseline` until the documentation item creates `demo`), prints the same summary and opens `report.html` in the default browser. No new options of the run; same settings, same run id and fingerprints (test `test_demo_equals_a_run_on_the_same_folder_by_fingerprints`).
- The version stays in three places that a fast test keeps equal: `project.yaml` (source), `actuarycanary.__version__` and `pyproject.toml`. The release workflow refuses a tag `vX.Y.Z[-suffix]` whose `X.Y.Z` is not the `project.yaml` version, and the built program's `--version` is checked against it. A pre-release tag such as `v0.1.0-rc1` is allowed for version `0.1.0`.
- `__version__` is not read from `project.yaml` at import: an installed package has no `project.yaml` next to it, and the run id contains the version.

## Consequences
- When the documentation item adds `examples/demo`, `canary demo` uses it with no change of code; the owner integrates both.
- A release needs the version raised in the three places first.
