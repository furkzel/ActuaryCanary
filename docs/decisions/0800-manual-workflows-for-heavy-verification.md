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

## Consequences
- **UNVERIFIED: the workflow has not run.** The file parses as YAML, uses the action versions of `ci.yml`, and names only recipes that exist in `justfile`; whether the suite fits into 90 minutes on a hosted runner is not known.
- Ground-truth comparisons on MOTOR_TPL may fail in the full run (0365, statement 1); that is information until P28.
