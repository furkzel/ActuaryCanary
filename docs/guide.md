# User guide

How to go from your own files to a report you can read and audit. For a first look without your own data, run the demo (see the [README](../README.md)) and follow this guide with its report open.

Everything the platform produces is an **indicative analysis** on the data you give it, never an official reserve, price or financial statement figure. Every page of the report says so.

## 1. What you need

- A computer with [uv](https://docs.astral.sh/uv/) installed. uv fetches Python 3.12 and the libraries by itself (`uv sync`).
- Your data as spreadsheets (`.xlsx`; `.xlsm`, `.xls` and `.ods` are read too), all in one folder.
- No server, no account, no network. Nothing leaves your machine, and the report page references nothing online.

## 2. Preparing the six input files

Version 1.0 reads **one spreadsheet per kind of data**, each holding one table. Only the claim valuations file is required. Every other file switches on more analyses; what is missing is listed in the report under "What did not run and why", never guessed.

| File | What it holds | Required columns (names are free, see below) | What it enables |
| --- | --- | --- | --- |
| `claim_valuations.xlsx` | The state of every claim at every valuation date (a snapshot per claim and month end): cumulative paid, case reserve, status, currency | claim, valuation date, paid to date, case reserve, status, currency | Everything about claims: triangles, chain ladder, anomalies |
| `claims.xlsx` | One row per claim: dates, segment, line | claim, occurrence date, report date, segment, line | Accident-period triangles, results by segment and line, reporting delay |
| `policies.xlsx` | One row per policy: cover period, segment, line | policy, start date, end date, segment, line, currency | Exposure, earned premium by period |
| `premiums.xlsx` | Every premium transaction: written, endorsement, cancellation, refund, commission | transaction, policy, booking date, amount, currency, type | Premium, loss ratios, Bornhuetter–Ferguson, Cape Cod, expected loss ratio |
| `expenses.xlsx` | Operating expenses by month and type | period, amount, currency, type | Expense and combined ratios |
| `market.xlsx` | Exchange rates and price indices by date | series, date, value, kind | Currency conversion and the inflation-adjusted view |

The full list of fields, types, allowed values and the quality rules of each file is in [spec/data/](../spec/data/). The file names above are what the platform proposes; it recognises a sheet by its **content**, so a differently named file works too.

Rules the files must follow ([CV07](../spec/conventions/CV07-input-files.yaml)):

- **One table per sheet**, no merged cells inside the table. Rows above the header (titles, notes, blank lines) are ignored and counted in the quality report. `market` may spread its series over several sheets, and a large feed may come in several workbooks (`policies_part1.xlsx`, `policies_part2.xlsx`).
- **Column names are free.** They are matched through a bilingual dictionary (English and Turkish), then fuzzy matching, then the look of the values. You confirm the result once (section 4).
- **Cumulative, not incremental.** Each valuation row says how much has been paid *in total* up to that date. A claim need not have a row for every month; the last row on or before a date is used.
- **Currency.** Amounts may be in several currencies; they are converted to the reporting currency (default TRY, from `project.yaml`) with the market file. Without a market file only amounts already in the reporting currency are used, and the rest is reported apart.
- **Personal data is never needed.** Columns recognised as personal data (names, identity numbers, customer numbers) are dropped when the file is read and only their names are listed.
- Text values are trimmed; an empty text counts as missing. Derived columns (quarters, development lags, ages) are ignored and recomputed.

A good first test of your files is to give the platform a copy and read the data quality section of the report before anything else.

## 3. Running it

```
canary run <folder>                 # the six files in <folder>
canary demo                         # the example data that ships with the program
```

`canary demo` is a command of its own, for a first look: it runs on [examples/demo](../examples/demo/) without asking, writes the report to `out/<run id>/` and opens it in the browser (`--no-open` does not open it, `--out` changes the output folder). It gives the same run id and outputs as `canary run examples/demo --yes`; it does not take your files, so for those use `canary run`.

`canary run` reads and recognises the sheets, asks you to confirm any new layout, checks quality, builds the triangles, runs the methods and writes the report and its manifest to `out/<run id>/`. The options that change what is computed:

| Option | Meaning | Default |
| --- | --- | --- |
| `--basis gross\|ceded\|net` | Reinsurance basis ([CV03](../spec/conventions/CV03-gross-ceded-net.yaml)) | gross |
| `--currency TRY` | Reporting currency | from `project.yaml` |
| `--value nominal\|inflation-adjusted` | Value basis; the adjusted basis restates paid to the prices of one date ([MT07](methods/MT07-inflation-adjusted-chain-ladder.md)) | nominal |
| `--value-date YYYY-MM-DD`, `--price-index SERIES` | Prices of this date, from this index series | cut-off, series of `project.yaml` |
| `--origin-axis accident\|report\|underwriting\|first_valuation` | What defines the origin period of a claim | accident |
| `--origin-period`, `--development-period` | Length of origin and development periods (month, quarter, half, year) | year, year |
| `--assumptions file.yaml` | Your judgements as a register: selected factors, exclusions, priors, future inflation, overrides | none |
| `--yes` | Do not ask; use saved profiles and, for new layouts, the proposals (not saved) | ask |
| `--out`, `--profiles` | Output folder, folder of mapping profiles | `out`, `profiles` |

Each change of basis is a new run with its own run id and manifest, so a report you printed can always be reproduced. (A report that switches bases on the page is planned for version 1.1.)

**An assumptions register** records who chose what and why; an entry without a reason is rejected before the run. For example, to select a tail factor of 1.1 and to exclude one link ratio:

```yaml
entries:
  - {method: MT02, name: tail_factor, value: 1.1, who: reviewer, when: 2026-01-05, why: long tail}
  - {method: MT02, name: exclusion, scope: NON_LIFE/PROPERTY/paid, target: '2023:12-24',
     value: true, who: reviewer, when: 2026-01-05, why: catastrophe year}
```

The entries in force, yours and the defaults they replace, are listed in `assumptions.csv`, in the report and in the manifest.

## 4. The mapping confirmation

The first time the platform sees a layout it cannot match to a saved profile, it shows each sheet as a table: your column, the canonical field it proposes, which layer matched it (`canonical`, `dictionary`, `fuzzy`, `values`), the confidence and the evidence. Green layers are exact matches, yellow ones are guesses to look at, and a column that is personal data says so.

For each sheet you answer:

- **a** (accept, the default): the proposal is used and **saved as a mapping profile** in `profiles/`; the next run with the same layout does not ask.
- **e** (edit): `3=claim_id` maps column 3 to a field, `3=-` leaves column 3 unused, `concept=claims` reads the sheet as another kind of data, `concept=-` skips it; an empty line ends editing and shows the table again.
- **s** (skip): the sheet is not used.

With `--yes` nothing is asked and nothing is saved: saved profiles are used, new layouts take the proposals. The run id includes the mappings, so the same data under another mapping is a different run. Confirmation needs an interactive terminal; in a script, use `--yes` or confirm once by hand first.

## 5. Reading the report

`report.html` is one self-contained file: open it in a browser, or print it to PDF from the browser (the print stylesheet gives A4 pages). Everything on it comes from one model: **every number links to its row in `lineage.csv`**, which names the measure or method, its version and the source rows, and every figure carries a footnote with the measure or method ID, version and basis.

The pages, in reading order:

1. **Cover.** Run id, valuation date (the cut-off), segments and lines, the bases chosen, the origin and development periods, claims used, input files, software version.
2. **Key findings.** Sentences from 23 fixed rules ([RP01](../spec/report/findings.yaml)); wording is a template with the numbers filled in, never free text. Each finding says where its evidence is. The most important ones are shown first and the rest are folded.
3. **At a glance.** Headline tiles per segment (written premium, incurred to date, ultimate loss ratio, reserve estimate), each with its change against the previous period, and a tile for the data quality score. Segments are shown separately and never added together.
4. **M01 Data understanding.** What was loaded: rows, first and last date and quality score of every file.
5. **M02 Portfolio and premium, M03 Claims experience.** By line: written, earned and unearned premium and average premium with the change against the previous year; reported and open claims, paid, case reserve, incurred, reporting delay, settlement time and large-loss share.
6. **M05 Profitability.** Loss, expense and combined ratios by line and accident period ([note](methods/RT01-loss-and-combined-ratios.md)).
7. **M06 Anomalies and large losses.** Payments and claims flagged by [MT08](methods/MT08-robust-z-score-flags.md) and [MT09](methods/MT09-isolation-forest-flags.md). A flag is a lead to review, never a verdict. A line where more than 5 per cent of the values are flagged is marked: it probably mixes populations.
8. **Reserving, one page per line** ([M04](../spec/modules/M04-reserving.yaml)). Triangles as heatmaps; link ratios with the selected factor; ultimates by method side by side ([MT02](methods/MT02-chain-ladder.md), [MT03](methods/MT03-bornhuetter-ferguson.md), [MT04](methods/MT04-cape-cod.md), [MT05](methods/MT05-expected-loss-ratio.md), the selection by [MT10](methods/MT10-ultimate-selection.md), and [MT07](methods/MT07-inflation-adjusted-chain-ladder.md) when asked); the [Mack](methods/MT06-mack.md) range drawn as 25–75 and 5–95 per cent bars; and the diagnostics.
9. **What did not run and why.** Every module or method that was skipped or limited, the reason, and what to load to enable it.
10. **Appendices.** Data quality (every rule that was touched: the rule ID, how many rows, five example rows with file, sheet and row number, and the modules affected; a score from 0 to 100); methods and assumptions (each method used, its version, parameters and assumptions in plain language); reproducibility (the manifest).

### The thin-evidence warning

When a triangle has **fewer than eight origin periods**, every triangle method says so and the report shows a banner: factors, ratios and ranges rest on few observations (decisions [0039](decisions/0039-diagnostic-thresholds.md) and [0064](decisions/0064-thin-evidence-threshold-confirmed.md)). With four origin years the Mack range does not run at all. The tiny examples ([baseline](../examples/baseline/), [messy_headers](../examples/messy_headers/)) have four accident years and show the warning on purpose; the [demo](../examples/demo/) has ten and does not. Read a thin-evidence report as an illustration of the layout, not as a result.

### Reading a reserve range

The Mack standard error assumes independent origins and stable development. On lines with strong calendar-year inflation or a long tail the range is too narrow ([decision 0062](decisions/0062-mack-coverage-is-a-property-of-the-data.md)); the report says so on such lines. The percentiles come from a lognormal approximation and are labelled as such. Use the ranges to see which lines are uncertain, not to set a precise confidence level.

## 6. The run folder

`out/<run id>/` holds fourteen files, all listed with their SHA-256 in `manifest.json`:

| File | Content |
| --- | --- |
| `report.html` | The report |
| `manifest.json` | Run id, input fingerprints, mapping profiles, settings, methods and versions, assumptions in force, seeds, output fingerprints |
| `triangles.csv`, `factors.csv`, `chain_ladder.csv` | Triangles of every group and basis; link ratios and selected factors; projected triangles |
| `ultimates.csv`, `reserve_range.csv` | Ultimate and IBNR by method and the selection (RS02); the Mack range (RS03) |
| `cash_flows.csv` | Expected future payments of the inflation-adjusted method |
| `measures.csv`, `lineage.csv` | Every measure value; for each, the source rows it came from (can be large: hundreds of megabytes for a million claim rows) |
| `modules.json`, `quality.json` | What each module ran and why; the data quality findings |
| `assumptions.csv`, `diagnostics.csv`, `anomalies.csv` | The register in force; the method diagnostics; every anomaly flag |

The same inputs, settings and software always give the same run id and byte-identical outputs. Spreadsheets are read once and cached as parquet files in `.cache/`, keyed by their SHA-256; delete the folder to force a re-read.

## 7. Examples

| Folder | What it is | Run id |
| --- | --- | --- |
| [examples/demo](../examples/demo/) | A synthetic insurer, ten accident years 2016–2025 and about 2,600 claims in four lines; no thin-evidence warning. The one to try first. | `86413bc4799ade00` |
| [examples/baseline](../examples/baseline/) | The same insurer at tiny size, four accident years 2022–2025, with a few faults injected on purpose | `4ecbe8130e88bcbb` |
| [examples/messy_headers](../examples/messy_headers/) | The baseline as real files arrive: headers renamed, misspelt or in Turkish, title rows above the header, dates as text, labels in Turkish, repeated rows and personal-data columns | `505e4ce901d9d375` |

Each example folder has the six input files and a `report/` folder with the report and manifest of its run (the report as the platform wrote it, the manifest with its fingerprints). The messy example is the one to use for the mapping confirmation: `canary run examples/messy_headers` asks about every sheet. The data are synthetic, generated from a fixed seed by [synthetic/scenarios/](../synthetic/scenarios/); no personal or company data is anywhere in the repository.

## 8. Size and memory

The demo and the tiny examples run in seconds on any laptop. The largest stress scenario (`large`: ten years and about a million claim valuation rows over six feeds, generated with `just synth baseline large`) loads, maps and reports in about 70–85 seconds cold on the development machine, but its **peak memory is about 7.4 GiB** ([decision 0082](decisions/0082-budget-on-six-feeds-of-large.md)); a machine with 8 GB may swap and be much slower. The two-minute budget on an ordinary laptop is not verified. Real portfolios of a few thousand to a few hundred thousand claims are well inside the demo-to-medium range.

## 9. Common problems

| What you see | Why | What to do |
| --- | --- | --- |
| `Cannot run: ... no sheet was recognised as claim_valuations` | No sheet has the required columns of the claim valuations, or the file is empty | Check the header row (rows above it are skipped, but the header must be one row); at the confirmation, map the sheet with `concept=claim_valuations` |
| `Cannot run: new layouts need confirming on the terminal; rerun with --yes` | No interactive terminal and no saved profile for a layout | Run once in a real terminal, or use `--yes` |
| `Settings rejected: ... needs a reason` | An assumptions register entry without `why` (or an unreadable file) | Add the reason; every user judgement must say who and why |
| `Cannot run: ... is not a link ratio of this triangle` | A register entry names an origin or column the triangle does not have | Targets are `origin:from-to` in months, for example `2023:12-24` |
| A module is `skipped` or `limited` | A feed it needs is missing, or its quality is too low | The "What did not run and why" page says which feed or rule |
| Report shows thin evidence | Fewer than eight origin periods | Add history, or read the report as an illustration |
| Many `DV-...` findings | Rules of the data specification are touched | Open the data quality appendix: each rule has its count and five example rows with file, sheet and row |
| Amounts missing or "not converted" | A currency has no rate in the market file (or there is no market file) | Add the series; premium booked before the first market date has no rate and is left out |
| Inflation-adjusted run refuses | The price index series is missing or does not cover the claims | Add the series to `market`, or pick another with `--price-index` |
| Many flags on one line in M06 | More than 5 per cent of the values flagged: the line may mix populations such as two currencies | Treat the flags as leads; check currency and status labels first |
| Strange characters in redirected output on Windows | Console code page | The command writes UTF-8 whatever the code page; open the file as UTF-8 |
| The page is slow to open | The report is about 5 MB (the chart library is inlined so that it works offline) | Wait a moment, or print to PDF once |

## 10. Where to go next

- The method notes in [docs/methods/](methods/): purpose, theory with formulas, assumptions and how to check them, a worked example with numbers computed by the platform's own code, references.
- The specifications in [spec/](../spec/): one file per rule, measure, method and module; every number in the report names the one that produced it.
- The decision records in [docs/decisions/](decisions/): why each choice was made.
- The [blueprint](blueprint.md): what the platform is and how it is built.
