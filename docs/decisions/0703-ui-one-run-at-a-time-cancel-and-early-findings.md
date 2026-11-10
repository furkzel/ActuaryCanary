# 0703 — One run at a time, cancel between stages, the findings as soon as they are on disk

## Context
`pipeline.run` takes a `progress` callback that receives the stage text; it reports nothing else while it runs. The item wants progress, elapsed time, the data findings "as soon as they exist", a cancel that stops between stages, a plain failure message and the folder of any partial output, and says pipeline code is not to be changed.

## Decision
- `ui/runner.py`: a `RunManager` starts `pipeline.run` in one daemon worker thread with the arguments the command line gives it (settings built by `ui/settings.py`, 0706; `profiles_dir`; `confirm=None`; the progress callback). A second start while a run is going is refused (`409`, code `run_busy`, message on the page); so is the demo.
- **Progress** is the stage list of `pipeline.run`, kept in `STAGES` with a Turkish text for each; the callback records the time of each stage. A test compares `STAGES` with the `step("...")` calls in the source of `pipeline.py`, so a new stage is not forgotten; a stage the page does not know is still shown with the pipeline's own text.
- **Cancel** sets a flag; the next call of the progress callback raises an exception that ends the run at the start of the next stage. A stage that has begun is finished; the last stage cannot be cancelled. The page says so next to the button.
- **Findings** are read from `quality.json` of the run folder, which the pipeline writes at the start of the stage "Writing the tables", before the report. The run folder is named by the run id, which the page does not know; the manager finds it as the newest folder under the output folder with a `quality.json` written at or after the start of the run (no slack, so an older run is not taken for this one). Before that stage the page says the findings appear once the data has been checked. This is the earliest point at which they exist on disk without changing the pipeline.
- **Failure.** The failures the command line reports as "Cannot run:" (`InputError`, `CanonicalError`, `TriangleError`, `ConversionError`, `ProfileError`, `AssumptionError`) are shown with their own text, as the terminal shows it. Any other exception is shown as `Type: message` with the last lines of the trace. A failed or cancelled run shows the partial folder found by the rule above.
- **State** is in memory only (the manager) and in the output folder. A closed tab does not stop the run; the page asks the server for the state when it opens and goes to the run screen when a run is going; a finished run is found on the Past runs screen.

## Consequences
- The data findings of a run that fails before "Writing the tables" are not shown (the failure message is).
- A run id folder that exists from an earlier run with the same id is rewritten by the new run; its `quality.json` carries the new time, so the early findings are the new ones.
