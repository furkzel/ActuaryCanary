# Changelog

Written for users. Versions follow semantic versioning; each specification file also carries its own version and change log.

## Unreleased

### What is new

- **Tier B reserving methods in the run.** For every segment and line the run now also fits the over-dispersed Poisson bootstrap (reserve distribution with percentiles, value at risk and simulated payments), the Munich chain ladder, Benktander blends, a fitted tail factor (shown, not applied unless you select it), the separation method and the frequency–severity projection, and back-tests the selection at 12, 24 and 36 months with the error of each method. A method that cannot run on a line says why, under "What did not run and why"; it never gives a number instead.
- **Claim sizes and extreme values.** Claim size distributions (lognormal, gamma, Weibull, Pareto) and a peaks-over-threshold fit of the tail are written per segment and line. The large-loss threshold stays the 99th percentile of claim sizes; the extreme-value threshold is only shown beside it. `project.yaml` may set another percentile or fixed thresholds in a `large_loss` section.
- **More outputs**, listed in the guide. The seeds and defaults of these methods are part of the run id.

Run ids of the three examples changed; the reserving tables of tier A (triangles, factors, chain ladder, ultimates, reserve range, cash flows, measures, lineage) are byte-identical to 1.1.0.

## 1.1.0 (2026-10-25, the preparation date: the release date is the date the owner pushes the tag `v1.1.0`)

### What is new

- **Report in Turkish.** `canary run <folder> --lang tr` writes the report in Turkish; the wording lives in `report/language.yaml`. Data messages, diagnostics, anomaly reasons and the wording of specifications stay in English.
- **Four new data rules:** DV-MKT-06, DV-MKT-07, DV-MKT-08 (market data) and DV-PRM-07 (premiums).
- **Reserve movements by kind.** The anomaly method MT08 (version 1.2.0) looks at reserve movements by kind, so far fewer movements are flagged on lines where reserves rarely change.
- **Lineage format 2.** The lineage of measures is written as `lineage_atoms.csv`, which is much smaller on large inputs. `--lineage-format 1` writes the previous format.
- **Original currency view.** There is an ORIGINAL currency view of the amounts, next to the reporting-currency view.
- **Cumulative or incremental claim amounts.** Whether claim amounts per period are cumulative or incremental is detected, and incremental amounts are accumulated.
- **Synthetic generator for more kinds of data.** It writes reinsurance treaties and treaty movements, recoveries, a ledger, interest rates and a life book (contracts, events, fund flows), with their ground truth, in the new scenarios `reinsurance_heavy` and `life_book`.
- **New tier B references.** 19 frozen reference sets (bootstrap, Munich chain ladder, Benktander, tail extensions, claim separation, frequency-severity, severity fits, survival, credibility, reinsurance and back-test cases) with tests that recompute every number.

The reserving tables of the three examples are byte-identical to 1.0.0.

## 1.0.0 (2026-10-23, the preparation date: the release date is the date the owner pushes the tag `v1.0.0`)

First release.

### What it does

- **Reads** one spreadsheet per kind of data (claim valuations, claims, policies, premiums, expenses, market) in any layout: header rows found by content, English and Turkish column names, fuzzy matching, text dates, local value labels. You confirm new layouts once on the terminal; the mapping is saved as a profile. Personal-data columns are dropped on load.
- **Checks data quality** against the rules of the data specifications, with a score from 0 to 100; every finding has its count, five example rows (file, sheet, row) and the modules it affects.
- **Builds triangles** (paid, incurred, case reserve, claim counts) for any origin and development period, per segment and line, on gross, ceded or net basis, in the reporting currency, nominal or inflation-adjusted.
- **Runs the methods**: chain ladder with selected factors and exclusions, Bornhuetter–Ferguson, Cape Cod, expected loss ratio, Mack standard error with a lognormal range, inflation-adjusted chain ladder with an explicit future inflation assumption, ultimate selection, robust z-score and isolation forest anomaly flags.
- **Computes measures** (premium, claims, frequency, severity, reporting delay, settlement, loss, expense and combined ratios, reinsurance, recoveries, data quality) with lineage to the source rows.
- **Writes one report**, an interactive single-file page that prints to PDF: key findings from fixed rules, headline tiles with the change against the previous period, a page per module, heatmaps, link ratios, ultimates by method, reserve ranges, diagnostics, what did not run and why, and appendices for data quality, methods and assumptions, and reproducibility.
- **Records everything**: a run manifest with fingerprints of inputs, mappings, settings, methods, assumptions and outputs; an assumptions register for your judgements (who, when, why). The same inputs always give the same run id and byte-identical outputs.
- **Works offline**: no network access, no account, no data leaves the machine.

### Documentation and examples

- A [user guide](docs/guide.md) and a note for each method with its theory, assumptions and a worked example computed by the platform's own code ([docs/methods/](docs/methods/)).
- Three synthetic examples with their reports: `demo` (ten accident years, about 2,600 claims), `baseline` and `messy_headers` (four accident years each, for testing).
- A check in `just check` that every link in the documents resolves, every specification ID they mention exists and the worked examples are what the code gives.

### Known limits

- Fewer than eight origin periods show a thin-evidence warning on every triangle method; with four origin periods the Mack range does not run.
- The report is static: another basis, currency or period is a new run with its own manifest (switching on the page is planned for 1.1).
- Mack ranges are too narrow where inflation, a long tail or an origin shock break the independence of origins; the report says so.
- Premium by underwriting period is not built, so Bornhuetter–Ferguson, Cape Cod and the expected loss ratio method do not run on the underwriting axis.
- The inflation-adjusted method has no IBNR and no tail factor beyond 1.0.
- The anomaly variable `reserve_change` flags a large share of the case-reserve movements on lines where reserves rarely change; the report warns when the flag rate of a line is above 5 per cent.
- The largest stress scenario (about a million claim rows over six feeds) needs about 7.4 GiB of memory at peak and has not been timed on an ordinary laptop.
- Not built: life and pension experience studies, treaty-level ceded allocation, discounted values, input shapes other than one table per sheet, and the tier B and C methods (bootstrap, Munich chain ladder, generalised linear models and others).
- Some checks were not done by hand: the report as a PDF page by page, the terminal confirmation in every terminal, the output on another machine. `HANDOVER.md` lists them.
