# 0304 — MT19 is built and callable, and no module calls it

## Context
The work item for MT19 (P25c) says: find the module specification that lists MT19; if one does, call the method from that module; if none does, leave the method callable, record that, and leave the report item (P27) to place it. `grep -l MT19 spec/modules/*.yaml` gives one file, M13 (model challengers, 0.1.0, `draft`, `implemented: false`, built by P35, no code). The older statements point elsewhere: record 0209 and the handover said M03 gains MT17 and MT19, and MT17 was wired into M03 in code in 0621 although the `methods` list of M03 does not name it (0622 left the module lists as they are). So the specifications place MT19 only in a module that is not built, and the earlier plan placed it in M03, whose specification does not list it.

The owner was asked on 2026-10-27 and chose not to wire it.

## Decision
- MT19 is implemented in `src/actuarycanary/methods/survival/` (Kaplan–Meier, log-rank, Cox, the Grambsch–Therneau test, concordance, the analysis per segment, the register entries) and `src/actuarycanary/modules/survival_run.py` (the durations of the claims of a run, `run_survival`, the tables and file names, the diagnostic rows, the settings). `implemented: true` in `spec/methods/MT19-survival-analysis.yaml`; the specification is otherwise unchanged (version 1.0.0).
- Nothing in `pipeline.py`, the manifest, the module runner or the report calls it. A run therefore does not write `survival_*.csv`, does not list MT19 in `specs`, and its settings record has no MT19 entry. Calling `run_survival(measure_inputs, settings.assumptions)` is the whole wiring; `survival_run.settings()` holds the defaults to add to the settings record at that point (`record["survival"]`), `SurvivalRun.files()` the tables for `write_table`, `diagnostic_rows` the rows for `diagnostics.csv`, `entries` the assumptions, `notes["M03"]` the refusals (a Cox model that could not be fitted, with its reason) for the module that is chosen.
- There is no seed: the method draws no random numbers, so it adds no row to `randomness`.

## Consequences
- `just golden` and `just examples` changed nothing: the golden copy is equal, and the run ids stay baseline `384dff36d777725f`, messy_headers `560f3c96c9ab3dca`, demo `465a16bea5dd8a65` (the manifest lists only the specifications of what ran; the flag alone moves nothing). Baseline and messy_headers still agree byte for byte in triangles, factors, chain ladder, ultimates, reserve range, cash flows and the tier B tables.
- The report item (P27) decides the module (M03 by amending its `methods` list, or M13 when P35 is built), calls `run_survival`, adds the settings, the files and the notes, and regenerates the golden copy, the examples and the guide once. What it must show is in HANDOVER ("Next").
- The tests of MT19 call the methods and `run_survival` directly; the wiring test of the pipeline is written by the item that wires it.
