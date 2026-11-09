# 0704 — The result screen and the past runs are read from the output folder

## Context
The result must be the same for a run started a moment ago, a run started in a tab that was closed, a run of an earlier start of the program and a run made by `canary run`.

## Decision
- `ui/summary.py` reads only files the pipeline wrote: `manifest.json` (run id, program version, language, currency, bases, cut-off used, inputs, how each sheet was read, tables not used, number of outputs), `quality.json` (score, findings by severity with their rule, count, message and first two examples) and `ultimates.csv`.
- **Headline numbers** are the table of the terminal summary: per segment and line, the sums over the origin periods of paid, incurred, ultimate and IBNR of the chain ladder on incurred amounts, with a total row. They are labelled with the currency, basis and cut-off of the run. The report carries every other method and the ranges; the page does not repeat them. A test compares the table with `RunResult.reserving` figures.
- **Past runs** are the folders under the output folder whose name is a run id and that hold `manifest.json`, newest first by the time of the manifest, at most 200. The date is the modification time of the manifest (the manifest holds no clock time, by design); language and basis come from its settings. Folders without a manifest (partial runs, `.cache`) are not listed.
- The report is served by the same server from the run folder (0700) and embedded in an iframe or opened in a new tab; it stays one self-contained file. "Open the output folder" asks the server to open the run folder in the file manager of the system (`os.startfile`, `open` or `xdg-open`), only for a folder that passed the run id check.

## Consequences
- A run folder of an older version of the program is shown as far as its files allow; a manifest that cannot be read is listed as such.
- No number on the page is computed by the interface; each is a number the pipeline wrote.
