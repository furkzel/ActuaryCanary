# 0090 — PyInstaller, one-folder build

## Context
A person without Python must download one archive, run one command and get a report (P11). Blueprint 14.2 asks for a downloadable executable. The program reads `project.yaml`, `spec/`, `synthetic/scenarios/`, the report templates, the plotly bundle and the example data at run time.

## Decision
PyInstaller 6, one-folder build, from `packaging/canary.spec`; added to the toolchain as a build-only dependency group (`build`) in `pyproject.toml`, owner-approved. The folder is zipped for the release. Alternatives rejected: Nuitka (compiles to C, builds take many times longer and need a C compiler in CI, no gain for a numerical program); one-file PyInstaller (unpacks 100+ MB to a temp folder on every start, slower start and a bigger antivirus surface).

The data files are placed at the root of the bundle (`project.yaml`, `spec/`, `synthetic/scenarios/`, `examples/`). The lookups that walk up from their own file (`find_project_file`, `find_spec_root`, `find_scenario_dir`, `find_demo_folder`) therefore find them inside the bundle with no change of code, and no repository is needed around the program.

## Consequences
- The program is not signed; Windows SmartScreen and some antivirus products may warn (UNVERIFIED, see HANDOVER).
- Only Windows is built (x86-64); other systems install from source.
- A new run-time data file needs a line in `packaging/canary.spec`; the smoke test in CI fails if it is forgotten.
- `build/` and `dist/` are git-ignored.
