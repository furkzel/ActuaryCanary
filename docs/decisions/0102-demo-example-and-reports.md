# 0102 — The demo example, the example reports and the screenshot

## Context
The tiny examples have four accident years: every group shows thin evidence (records 0039 and 0064) and the Mack range does not run, so they cannot show a stranger what the report looks like. P12 asks for a demo with at least eight origin years and a few thousand claims, small enough to ship, from a fixed-seed scenario, with its report.

## Decision
- **Scenario.** `synthetic/scenarios/demo.yaml` extends `baseline`, sets its own seed (20261023) and adds a size `demo`: `portfolio_scale` 0.012, the baseline's group-life exposure multiplier, injected faults at half the baseline count. It keeps the ten accident years 2016 to 2025. Only 0.012 was tried: 2,591 claims in four lines, 23,166 valuation rows, six spreadsheets of 5.9 MiB in all, about 30 seconds to generate, no thin-evidence banner.
- **Files.** `examples/demo/` holds the six spreadsheets only, as `examples/baseline` and `examples/messy_headers` do. They are written by `just examples` (`docs/tools/refresh_examples.py`) from the scenario, and a slow test checks that the committed files are what the scenario writes today.
- **Reports.** Each example folder has `report/report.html` and `report/manifest.json` of the run with default settings (new layouts take the proposals, no saved profile). The reader looks only at spreadsheets in the top level of a folder, so the subfolder does not disturb a run. The other twelve output files are not committed (`lineage.csv` alone is large). A fast test checks the report's SHA-256 against its manifest; a slow test checks the run id of a fresh run against the manifest. The three reports are about 5 MB each because the chart library is inlined; the repository grows by about 15 MB before compression.
- **Run ids** (default settings): baseline `4ecbe8130e88bcbb` (the golden copy), messy_headers `505e4ce901d9d375`, demo `86413bc4799ade00`. The guide names them and a test keeps them current.
- **Screenshot.** `docs/images/report-demo.png` is the top of the demo report (cover, key findings, first tiles), taken with a headless browser at 1300 pixels wide. It is a snapshot of one run: retake it when the report layout changes.
- **Version.** `project.yaml` and `pyproject.toml` keep 0.1.0; the changelog entry 1.0.0 is marked not yet released. The version is part of the manifest and so of the run ids and the golden copy; the owner sets it at release and then runs `just golden` and `just examples`.

## Consequences
- The demo report shows no thin-evidence banner; M06 is `limited` because some groups flag more than 5 per cent of their values (the `reserve_change` variable, known and accepted, see HANDOVER).
- `canary demo` (packaging item) reads `examples/demo/`; until the owner integrates both, README and guide describe it as the same as `canary run examples/demo`.
- Whenever the report or a method changes, `just examples` changes the three reports; read the diff.
