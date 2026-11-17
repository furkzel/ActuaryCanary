# 0816 — C1: the demo's confirmed profile ships with the program; the refresh tool keeps it

## Context
Record 0812 made the demo run on the confirmed ledger profile that lies beside its committed report, so that `canary demo`, the interface's demo and `canary run` give the committed run id. The Windows program did not carry that file and proposed the profile (another hash, another run id), and record 0814 found that `refresh_examples.py` confirmed the profile anew on the day it runs, which moved the demo's run id by the date.

## Decision
- **The program carries the profile.** `packaging/canary.spec` adds `examples/demo/report/ledger-*.yaml` to the bundle beside the demo workbooks and stops the build when none is there. `cli/demo.py` starts its lookup at `sys._MEIPASS` in a frozen program (`program_root`) and at its own file otherwise; the walk upwards, `place_demo_profiles` and the demo itself are unchanged.
- **The smoke tests compare like with like.** The source run of `package.yml` and `release.yml` now reads the same profile (`--profiles examples/demo/report`); without it the source run would propose the profile and its manifest would differ from the program's. The session did not commit the two workflow files; the change is saved as `docs/release/workflow-demo-profile.patch` for the owner to apply with `git apply` (a test accepts either state).
- **The refresh tool never rewrites a shipped profile.** `run_example` copies the profile an example ships beside its report into the run's profiles folder unchanged and runs once; only an example that ships none gets the profile its first run proposed confirmed with today's date and runs again. `write_reports` reads the shipped bytes before it clears the report folder, writes them back unchanged and returns the run ids. A full refresh clears the demo folder, so a regenerated demo gets a profile confirmed that day, as before.

## Consequences
The demo's run id no longer depends on the day of a refresh, and the program's demo and a source run give one run id (UNVERIFIED on Windows: the program cannot be built here; the lookup is tested with a simulated frozen layout). A person who regenerates the demo data has to commit the new profile with it.
