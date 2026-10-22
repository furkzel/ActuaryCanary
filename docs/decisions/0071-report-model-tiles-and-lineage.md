# 0071 — The report model, the headline tiles and lineage of method outputs

## Context
Blueprint 11 orders the report and asks that every number be traceable; blueprint 12 asks that every number link to a lineage row. `lineage.csv` covered the measures computed from the feeds but not the method outputs RS01–RS03 that the reserving page shows.

## Decision
- `report/model.py` builds one JSON-ready dictionary with every number and text of the page, rounded per CV06; the template only draws it. Table rows carry the measure rows behind them (`MEASURE [view] rows n, …`, the keys of `measures.csv` and `lineage.csv`), shown on hover; every table and figure has a footnote with spec IDs, versions and basis.
- Order of the page as in blueprint 11: cover, key findings, at a glance, one page per module that ran (M01, M02, M03, M05, M06), reserving (summary, then one page per segment and line with heatmaps, factors with the selection, ultimates by method side by side, the Mack range, diagnostics), what did not run, the quality appendix, the methods and assumptions appendix, the reproducibility appendix. The earlier list of every measure view moves into the methods appendix.
- Tiles per segment (segments are never added): written premium of the latest calendar period against the one before, compared only when the cut-off closes the period; incurred to date and selected IBNR against the previous valuation point of the development grid (the selection recomputed there with `earlier_result`, as AE01 does); ultimate loss ratio of the latest origin against the previous origin, in points; one data quality tile without a comparison, because no earlier run is stored. A segment IBNR tile shows no range, because ranges of lines do not add.
- Lineage of RS01–RS03: the claim_valuations rows up to the cut-off of the claims of the row's segment, line and origin period; a row without an origin (a development column, a total) gets the rows of its whole segment and line, because its factors rest on every origin. `lineage.csv` grows by about a fifth on the tiny baseline. Measures still without lineage rows (AE01, RT02, CL10, DQ01) are named in the appendix; they derive from other measures or from `quality.json`.
- The data files are written before the page, so the reproducibility appendix lists their fingerprints; the page and the manifest are fingerprinted in the manifest only.

## Consequences
- `RunResult.report_data` holds the model; the golden test compares it (0074).
- The assumptions register is not duplicated: `assumptions.csv` stays the file; the appendix summarises it by method and parameter and lists the judgements of users.
