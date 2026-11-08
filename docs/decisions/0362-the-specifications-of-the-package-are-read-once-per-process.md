# 0362 — The specifications of the package are read and checked once per process

## Context
`load_specs()` reads 1,210 yaml files, validates each against its model and checks every reference, 0.3 s on this machine without a profiler (0.75 s under cProfile). A run calls it once; the test suite calls it from a dozen modules at import time (`SPECS = load_specs()`), so each of the (up to six) test workers paid it ten times while collecting 1,883 tests. Profiled collection (`pytest --collect-only -n0`, this machine): `load_specs` 7.5 s of 23 s under the profiler, 10 calls. The fast suite on the CI runner was 37.1 s for 1,698 tests (0363), about 17 s of it before the first test ran (record 0363).

## Decision
`load_specs(root=None, planned=...)` keeps its result per process when no `root` is given: the catalogue of the package itself, built and planned, is read and checked on the first call and handed back afterwards. A `root` is always read afresh (the loader-error tests copy specs into a scratch folder and break them). The catalogue is a frozen dataclass of validated models, and its properties build new dictionaries on each access, so sharing it cannot be seen by a caller; the full suite was run to confirm it. No number can change: the same files are read by the same code.

This is the "avoiding repeated validation" of the hardening item: `canary run` itself loads the specifications once, so a single run gains nothing.

## Result (ran 2026-11-08)
- Collection of the fast suite: 14.2 s -> 11.5 s (`pytest --collect-only -n0`, this machine).
- `tests/spec/test_loader_errors.py::test_the_specs_of_the_package_are_read_once_and_a_root_is_read_afresh`: the same object twice for built and planned, the two different, and an empty root still raises `SpecError`.
