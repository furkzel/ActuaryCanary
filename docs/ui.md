# The browser interface (`canary ui`)

A prototype for people who do not use a terminal. It runs on your computer only and calls the same code as `canary run`: the same settings give the same run id and the same files.

## Start it

```
canary ui
```

It prints an address (`http://127.0.0.1:<port>/?t=<token>`) and opens it in the browser. `--no-open` only prints it; `--out` and `--profiles` set the folders the page starts with; `--lang tr` starts it in Turkish. Stop it with the Quit button of the page or Ctrl+C. Reopen the printed address in another tab if you closed yours: a run that was going continues, and finished runs are under Past runs.

## What it does

1. **Start.** Choose the folder with the Excel files (type the path or Browse; the browser lists drives and subfolders with the number of spreadsheets), the output folder, and the settings of `canary run` (currency, reinsurance basis, value basis and curve, dates, language, and under More settings the periods, origin axis, currency view, price index, lineage format, assumptions file, profiles folder). The page shows the command line the choices correspond to. Buttons: Check the files, Run now (like `--yes`), Run the demo.
2. **What was recognised.** For each sheet: the kind of data, the confidence, the header row, and how each column was mapped (layer, confidence, evidence). Change a column's field from the list, mark it not used, change the kind of data, or say whether claim amounts are cumulative or per period; then confirm. The confirmed mapping is saved as a profile in the profiles folder, where `canary run` reads it too. Workbooks with nothing the program can use, or that cannot be read, are listed with the reason.
3. **Run.** The stages of the pipeline with the time of each, the elapsed time, the data findings as soon as they are on disk, a Cancel button (stops before the next stage), and, if the run fails, the same message as the terminal and the folder of any partial output.
4. **Result.** Headline numbers (the table of the terminal summary), the data findings, the run id, how the sheets were read, links to open `report.html` (new tab or here), to open the output folder, and a button to run again.
5. **Past runs.** The run folders under the output folder: run id, date, language, basis, and buttons to open the result, the report and the folder.

## Where it writes

Under the output folder (`<out>/<run id>/` and `<out>/.cache`), and, when you confirm a mapping, in the profiles folder (default `profiles` in the folder the program runs in, as for `canary run`). The demo writes to a temporary folder. It deletes nothing and sends nothing anywhere.

## What it does not do

- Only the recognition, mapping, run and report path; no other command of the program (`info`, `synth`, ...).
- Spreadsheets only (`.xlsx`, `.xlsm`, `.xls`, `.ods`); `.csv` files are counted but not read, as on the command line.
- No progress inside a stage, and cancel only between stages.
- No editing of the assumptions register, `project.yaml` or the large-loss threshold; the assumptions file is a typed path.
- No comparison of runs, no deleting of runs, one run at a time.
- Not checked in Firefox or Safari or with a screen reader; the layout was looked at in Microsoft Edge only (see `HANDOVER.md`).

Design records: 0700 to 0706 in `docs/decisions/`.
