# 0022 — Component interfaces of the first end-to-end slice

## Context
P04 builds the first path from spreadsheets to a report. Later items (recognition, quality, conversion, more methods) must replace or extend single components without rewriting the path, so each component's input and output is fixed here.

## Decision
| Component | Function | Takes | Returns |
| --- | --- | --- | --- |
| io | `read_workbook(path, cache_dir)` | a spreadsheet; cache folder or None | `Workbook`: name, SHA-256, size, one `RawTable` per sheet; every row has `_source_file`, `_source_sheet`, `_source_row` (spreadsheet row) |
| canonical | `canonicalise(table, spec)` | a `RawTable` whose columns use canonical names; a data concept spec | `CanonicalFeed`: typed polars frame (spec fields present + source columns), `Finding`s (concept, rule ID, severity, count, first 20 source rows) |
| convert | `development_rates(reporting_currency)` | the reporting currency | rate per original currency (CV01 constant development rate) |
| structures | `build_triangles(valuations, claims, settings, rates, currency)` | canonical frames; `TriangleSettings` (MT01 parameters) | `TriangleSet`: `Triangle`s per measure and (segment, line) as numpy arrays (NaN = not observed), claim counts, valuation-point index per cell; unconverted totals; findings |
| methods | `chain_ladder(cumulative, **MT02 parameters)` | 2-D numpy array, optional diagonal index per cell | `ChainLadder` (link ratios, factors, CDF, ultimates, projection, flags) or `Skipped(reason)` |
| modules | `run_reserving(triangles, settings)` | `TriangleSet`, `ChainLadderSettings` | `ReservingResult`: per group, triangles and chain ladder on paid and on incurred; RS02 rows per origin |
| report | `render_report(context)` | `ReportContext` (results, findings, inputs, specs, settings, run id) | the HTML page as text |
| manifest | `run_id(...)`, `write_output(...)`, `write_manifest(...)` | records of inputs, specs, settings, outputs | run id; written files with fingerprints |
| pipeline | `run(folder, out_root, settings, cache_dir, progress)` | input folder; `RunSettings` | `RunResult` |
| cli | `canary run <folder> [--out] [--origin-period] [--development-period]` | | exit 0, 1 (input), 2 (settings) |

- All functions are pure apart from `read_workbook` (cache) and the writers, which write only into the cache and the run folder.
- Methods work on numpy arrays, so benchmark triangles and built triangles use the same code; structures and canonical work on polars frames.
- `pipeline.py` is a module at package level: it only calls components in order; the CLI only parses options and prints.
- Figures are plain plotly JSON drawn by the inlined plotly library, not `plotly.graph_objects`, so the page is byte-identical between runs and builds in milliseconds.
- Unrounded data files `triangles.csv`, `factors.csv`, `chain_ladder.csv` are written next to the report (CV06).

## Consequences
- Recognition (P05) renames columns before `canonicalise`; the quality profiler reads `CanonicalFeed`s; market conversion replaces `development_rates`.
- A new method is one function on arrays plus a line in `run_reserving`.
