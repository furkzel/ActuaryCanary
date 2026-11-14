# 0420 — Headroom of the fast suite

## Context
The fast suite ran 28.99 s at the end of F2a against the limit of 30 s. F2b adds tests, so it starts by making room, without removing or weakening a check. The one run of the fast suite with `--durations=40` this item allows (the exception to the single `just check`) was made on the session's machine (4 cores, shared): it took 43.4 s in that run, 31 to 60 s in the later runs; the times of this machine are noisy and are not the times of the CI runners (26.7 s on Ubuntu for `main`), so the comparison below uses runs of the same machine, one after the other.

## What the durations showed
No test body is slow: the top of the list is fixture *setup* (3 to 5 s each: `test_messy_incremental`, the scenario folders written and read for `test_new_feeds`, `test_scenario_faults`, the `cli_run` and `default_run` runs, the UI server test). The same module fixture was built by each worker that got one of the module's tests, because xdist's default distribution sends tests of one module to several workers.

## Decisions
- `pyproject.toml`: pytest runs with `--dist loadscope`, so that the tests of one module (or class) stay on one worker and a module-scoped fixture is built once instead of up to four times. CPU time of the run fell from 1 m 57 s to 1 m 46 s (same machine, same tests), the wall time from 34.2 s to 32.1 s, without changing any test.
- `tests/synthetic/test_messy_incremental.py`: the two scenario folders it wrote itself (`messy_headers`, `messy_incremental`, about 2 s each) now come from the session-shared `scenario_folder` fixture that the other test files already use, so each scenario is written once per session.
- Nothing is removed, shrunk or marked slow: no single test was above 0.5 s in its call phase except those already marked.

## Consequences
- Measured on the same machine: fast suite 43.4 s before (first run), 31.2 s after the first change (`loadscope`), the later run of the unchanged default distribution 60.2 s: the machine's own spread is larger than the gain, so the gain is stated in CPU time (about 9 %) and the CI runners will tell the rest.
- `test_properties_hold_with_the_index_clause` (F2a, `tests/methods/test_mt21_reinsurance_application.py`) failed once in the default-distribution run with the Hypothesis example `payments=[117, 4], retention=0, extra=1`: the ceded incurred of the layer with retention 1 was 0.10 above that with retention 0. The test is F2a's and F2b may not change the methods; it is listed for the owner (a real property of the indexed layer, or an index factor applied to retention and limit differently) and Hypothesis keeps the example in its local database so that it can be replayed.
