# 0800 — Manual workflows for the heavy verification

## Context
The full suite, the Monte Carlo tests, the `large` benchmark and the Windows build take too long for a working session. They move to GitHub as workflows that start only by hand (`workflow_dispatch`: Actions tab, the workflow, "Run workflow", branch `main`). Each writes a short result into the job summary.

## Decision
**`full.yml`** — Ubuntu and Windows, `fail-fast: false`, 90 minutes per job, read-only token. Setup as in `ci.yml`, then the medium folders below, then the body of `just test-all` with one test left out: `uv run pytest -n auto -q -rs -k "not medium_runs_inside_its_budget"`. The last 30 lines of the pytest output go into the job summary.

The medium budget test is left out because its budget needs a reference machine; it keeps its own non-blocking job `budget` in `ci.yml` (0361).

Medium folders generated (`just synth <scenario> medium`), from the tests that skip without them:

| Scenario | Tests that read `data/synthetic/<scenario>/medium` |
| --- | --- |
| `baseline` | `tests/measures/test_ground_truth.py`, `tests/structures/test_mt01_ground_truth.py`, `tests/structures/test_bases_ground_truth.py`, `tests/test_pipeline_tier_b.py`, `tests/methods/test_mt07_inflation_adjusted.py`, `test_mt08_robust_z.py`, `test_mt09_isolation_forest.py`, `test_tier_b_ground_truth.py`, `survival/test_survival_ground_truth.py`, `severity/test_severity_ground_truth.py` (and the budget test, left out) |
| `high_inflation` | `tests/methods/test_mt07_inflation_adjusted.py`, `test_mt08_robust_z.py`, `test_mt09_isolation_forest.py`, `test_tier_b_ground_truth.py` |
| `large_loss` | `tests/methods/severity/test_severity_ground_truth.py` |
| `reserve_bias_change` | `tests/methods/test_tier_b_ground_truth.py` |

No test reads a medium folder of `life_book`, `messy_headers`, `reinsurance_heavy` or `demo`; tests that call `simulate(...)` build their data in memory and need no folder.

**`heavy.yml`** — two jobs on Ubuntu, 120 minutes each, read-only token.
- `montecarlo`: `ACTUARYCANARY_MONTE_CARLO=1 uv run pytest -n 6 -q -rs --durations=10` on the test files that mention the flag, found by `grep -rl` at run time so that a new Monte Carlo file is picked up without editing the workflow. Today these are seven files: `tests/modules/test_uncertainty_monte_carlo.py`, `tests/methods/test_mt06_mack.py`, `test_mt11_odp_bootstrap.py`, `test_mt11_cut.py`, `survival/test_survival_monte_carlo.py`, `severity/test_severity_monte_carlo.py`, and `severity/test_mt18_extreme_values.py` (the flag only in a comment; its tests run as well). None of them reads a medium folder, so the job generates no data. The summary holds the count line and the ten slowest tests.
- `bench`: `just synth baseline large`, then `just bench data/synthetic/baseline/large`. Both commands run under `/usr/bin/time -v` (when the runner has it), which gives the peak memory of the command with its children. The summary holds the bench table (each step, cold and warm) and the peak memory and wall clock of the generator and of the two passes.

**`package.yml`** — Windows, 60 minutes, read-only token: `uv sync --group build`, `just package`, the smoke test of `release.yml` copied exactly, a zip of `build/dist/canary` uploaded as the artifact `windows-snapshot`. The summary holds the version the program prints, the size of the zip and the last line of `packaging/compare_manifests.py` (run once more for the summary). `release.yml` still runs by hand as a snapshot build and is left as it is.

**`release.yml`, last step only** — if `gh release view <tag>` succeeds, the archive is uploaded to the existing release (`gh release upload <tag> actuarycanary-*.zip --clobber`); otherwise the release is created as before. The owner can then make the tag from the GitHub release page on a phone without the workflow failing on a release that already exists.

## Consequences
- **UNVERIFIED: none of the workflows has run.** The files parse as YAML, use the action versions of `ci.yml` and `release.yml`, and name only recipes that exist in `justfile`; the shell of the summaries was tried on sample output only. Not known: whether the suite fits into 90 minutes and the Monte Carlo tests into 120 on a hosted runner, the peak memory of the generator on `large` (if the runner runs out of memory the job fails, which is information), and whether the runner has `/usr/bin/time`.
- Ground-truth comparisons on MOTOR_TPL may fail in the full run (0365, statement 1); that is information until P28.
- **UNVERIFIED: the changed step of `release.yml`**, until a tag is pushed (both branches: release exists, release does not exist).
- After the merge the owner starts `full`, `heavy` and `package` once each on `main` and reads the three summaries; `just test-all`, the Monte Carlo tests and `just bench` on `large` are no longer run inside a working session.
