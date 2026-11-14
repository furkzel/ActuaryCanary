# Changelog

Written for users. Versions follow semantic versioning; each specification file also carries its own version and change log.

## 1.3.0 (2026-11-14, the preparation date: the release date is the date the owner pushes the tag `v1.3.0`)

### What is new

- **Four new feeds and four new modules.** `reinsurance_treaties`, `reinsurance_transactions`, `recoveries` and `ledger` are read and checked. M07 Recoveries (recoveries to date, by type and development), M08 Reinsurance (the treaty programme applied to the gross claims in the inuring order, allocation to claims and policies, reconciliation with the booked amounts, a what-if page), M09 Expenses and M10 Ledger reconciliation (gaps between the platform's figures and the ledger by entity, class and month, with suggested causes and the share of the books no account rule maps) have their own pages in English and Turkish. The ledger account-mapping profile is saved beside the column profiles; a new one is proposed and labelled "not confirmed" until `confirmed_on` is set.
- **Reinsurance index clause.** The setting `reinsurance.index_clause` is `payment_by_payment` (default) or `occurrence_date`.
- **New finding rules** KF35 to KF49 on the new modules.
- **Review fixes.** Presentation (the curve table, the bridge to the simulated mean, one name for the selected unpaid, coverage and the number of back-tests beside every range, the failed checks beside the data quality score); a rule for development factors that rest on fewer than two link ratios (replaced by 1.000, disclosed beside the average); diagnostics of the bootstrap.
- **A stable bootstrap.** The refit of the bootstrap no longer lets a thin late column blow up the factor: columns with too few link ratios take 1.000, no pseudo increment goes below zero, and the default is 50,000 simulations. Seed stability over 20 seeds is 2.14 % (VaR 99.5 %) and 2.21 % (TVaR 99 %) against a target of 2 %, not met by a hair.
- **Generator fixes** behind the demo: the claim size of sum-insured lines follows the calendar day, the reserve of a claim that closes at nil is capped, ceded premium starts with the first treaty period.
- **The demo shows all four modules.** `examples/` carries every feed; the demo's ledger profile is confirmed. Run ids of the three examples changed.
- **Manual CI workflows** `full`, `heavy` and `package` (start by hand; none has run yet) and the first version of `canary ui`.

### Known limits

- Not checked at this release: the three manual workflows, the Windows run, the Monte Carlo tests, the benchmark, the page by eye.
- The seed stability target of 2 % is missed by 0.14 and 0.21 points.
- Two runs on the same inputs differ in the last digit of some reinsurance sums, so their output files are not byte-identical (the run ids are).
- The demo shows findings that stem from the generator (the claims of the TPL treaty follow the occurrence-date clause; the rate convention of the ledger's reinsurance account); see `examples/README.md`.
- The medium-size run takes longer than its time budget on slow machines; `just bench` on the large scenario takes more than two minutes on a laptop.

## 1.2.0 (2026-11-09, the preparation date: the release date is the date the owner pushes the tag `v1.2.0`)

### What is new

- **Tier B reserving methods in the run.** For every segment and line the run now also fits the over-dispersed Poisson bootstrap (reserve distribution with percentiles, value at risk and simulated payments), the Munich chain ladder, Benktander blends, a fitted tail factor (shown, not applied unless you select it), the separation method and the frequency–severity projection, and back-tests the selection at 12, 24 and 36 months with the error of each method. A method that cannot run on a line says why, under "What did not run and why"; it never gives a number instead.
- **Claim sizes and extreme values.** Claim size distributions (lognormal, gamma, Weibull, Pareto) and a peaks-over-threshold fit of the tail are written per segment and line. The large-loss threshold stays the 99th percentile of claim sizes; the extreme-value threshold is only shown beside it. `project.yaml` may set another percentile or fixed thresholds in a `large_loss` section. The standard errors of the severity fits use analytic second derivatives, and a single Pareto II fit now finishes.
- **Survival analysis.** Kaplan–Meier curves with confidence intervals and percentiles, and Cox regression with its tests, are available and appear in the report.
- **Uncertainty.** Reserve ranges from the Mack method and from the bootstrap, with value at risk and tail value at risk, and a simulated total of all lines.
- **Discounting.** Interest rates are read as a feed (`interest_rates`), yield curves are built from them, and unpaid amounts and cash flows can be shown as present values (`--value discounted --curve <curve_id>`). The demo ships an `interest_rates.xlsx` with the curve `TRY_GOV` and names it, so its report carries the discounted figures.
- **Sensitivity tables** of the reserve to the main choices are rerun inside the run.
- **Value basis switch in the report.** The page switches between the nominal and the discounted basis without a new run.
- **New finding rules** KF27 to KF34 on the tier B results; KF28 needs a consistent sign of the back-test errors, KF31 tests a fixed shape and KF32 needs a ratio of 1.25 between the longest and the shortest median settlement time.
- **The bootstrap on short-tail lines.** Late development columns that carry no payments (or only small recoveries) are cut before the bootstrap is fitted, so the bootstrap range and the simulated total of all lines now exist for lines that used to fall back to the Mack range; the cut is stated in the output files and on the uncertainty page.
- **Platform-identical output files.** The tier B, severity and survival files are written to 10 significant digits and are byte-identical on Windows and Linux.
- **Turkish golden copy.** The Turkish report is held to a golden copy of its own, beside the English one.
- **More outputs**, listed in the guide. The seeds and defaults of these methods are part of the run id.

Run ids of the three examples changed.

### Known limits

- The medium-size run takes longer than its time budget on slow machines; the CI `budget` job is the reference.
- `just bench` on the large scenario takes more than two minutes on a laptop.
- Premium by underwriting period is not built; Mack and bootstrap ranges still disagree by more than 30 % on some demo lines; the line correlation in the simulated total is 0.

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
