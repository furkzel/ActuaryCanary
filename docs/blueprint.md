# Actuarial Data Science Platform — Blueprint

Version 0.1 (draft)

A language-neutral blueprint for an open-source platform that reads any insurance dataset, understands it, and turns it into actuarial analyses and an executive report. Every rule is written as data and formulas, so the platform can be built in any language, in a spreadsheet, or by hand.

## 1. Vision and scope

The platform is an open, local, single-user tool: a person loads insurance data files, the platform recognises what they contain, checks their quality, builds the actuarial structures, runs the methods, and produces an executive report. It covers non-life, life and pension business, gross, ceded and net, and every feed is optional.

**Who it is for.** Anyone who downloads it and runs it on their own computer. No server, no account, no data leaves the machine.

**What success looks like.** A team can replace hours of manual spreadsheet work with one load-and-report run, trust the numbers because every figure is traceable, and adopt it without a migration project.

**Three phases.**

1. **Understand and analyse (phase 1).** Read any tabular file, map it to the canonical model, report data quality, compute the measures and the tier A methods, and produce the executive report.
2. **Deepen (phase 2).** Tier B and C methods, uncertainty and risk measures, life and pension experience studies, data science challengers, scenario and sensitivity tools.
3. **Govern (phase 3, optional packs).** Roles, data contracts, an append-only governed store, closing workflow, four-eyes approval, control library and hash chains. These depend on each company's regulation and team culture, so they are optional packs on top of a core that already works without them.

**Out of scope in phase 1:** roles and permissions, data contracts, a governed store, closing and controls, official reserve figures, pricing decisions, any company-specific content.

**Hard limits in every phase.** All outputs are indicative analyses, never official reserves or prices. The platform never needs personal data, and its sample data is synthetic.

## 2. Design principles

The order below is the tie-breaker: when two principles conflict, the higher one wins.

1. **Auditability.** Every number in every output can be traced back to the input rows, the column mapping, the parameters and the method version that produced it. An unexplained number is a defect.
2. **Inheritability.** A newcomer can understand any rule from its specification file without reading code. Every rule has exactly one specification. Every decision has a decision record.
3. **Reproducibility.** The same inputs, configuration and method versions always give the same outputs, bit for bit. Randomness is seeded and the seed is recorded.
4. **Correctness before breadth.** A method enters the platform only with a written specification, a ground-truth test on synthetic data and, where one exists, a match against a published benchmark.
5. **Modularity and graceful degradation.** Every feed is optional. Each analysis declares the feeds and fields it needs. When something is missing, the analysis is skipped with a stated reason, never filled with guesses.
6. **Separation of layers.** Reading, understanding, structuring, computing, measuring and presenting are separate steps with data contracts between them. No layer reaches past its neighbour.
7. **Configuration as data.** Mappings, aliases, thresholds, method choices and report layouts are data files, not code. A user changes behaviour without programming.
8. **Indicative, labelled, honest.** Every analytic output says what it is (indicative), what it assumes and how uncertain it is. Ranges beat point estimates.
9. **Privacy by design.** No analysis needs personal data. Identifying columns are recognised and dropped at the door.
10. **Clean code culture.** Small pure functions, explicit names in the domain's language, no hidden state, one way to do each thing, tests next to rules, documentation as part of done.

## 3. Architecture at a glance

```
Files in any layout
  -> Reader (raw tables, every row keeps file/sheet/row)
  -> Recogniser + mapping profile (shape and concepts, five-layer column mapping, user confirms)
  -> Canonical feeds + quality report (personal data dropped, six quality dimensions)
  -> Converter + structure builder (currency, inflation, gross/ceded/net; triangles, exposure, cohorts)
  -> Measures + methods (measure catalogue, tier A/B/C methods, challengers)
  -> Module runner (runs modules whose concepts exist, explains the rest)
  -> Executive report (interactive page + printable document, identical numbers)

Used by every step: specifications, configuration, assumptions register, run manifest, lineage table.
Phase 3 governance packs attach to the canonical feeds.
```

Files move down one path, each step with a data contract to the next (section 14). The records on the right are written by every run and are what make any number traceable; the governance packs attach to the canonical feeds in phase 3 without changing the path.

## 4. Data concepts

This section describes what the platform understands, not what a user must deliver. The twenty concepts below, in four families, are the canonical target; no input file has to look like any of them. Real data usually arrives in other shapes: one cumulative extract with policies, claims and payments on the same row, monthly cumulative files per partner, or everything in one sheet. Section 6.2 explains how such files are split into these concepts.

Fields marked \* are the minimum for a concept to be built, from whatever source. When they cannot be found or derived, only the analyses that need that concept are skipped.

### 4.1 Reference data

| Feed | Grain | Key | Core fields | Classes |
| --- | --- | --- | --- | --- |
| Entity | one legal entity | entity\_id\* | name, country, reporting currency\* | entity type: insurer, reinsurer, pension company |
| Business hierarchy | one node | node\_id\* | parent\_id\*, level\*, code, label | level: segment > line > subline > product > coverage; segment: NON\_LIFE, LIFE, PENSION, HEALTH |
| Calendar | one day | date\* | month, quarter, year, fiscal period, business day flag | period type: MONTH, QUARTER, HALF, YEAR |
| Currency | one code | currency\_code\* (ISO 4217) | minor units, label | currency role: ORIGINAL, FUNCTIONAL, REPORTING |
| Distribution | one channel or partner | channel\_id\* | channel type, partner name | channel: AGENCY, BROKER, BANK, DIRECT, DIGITAL, PARTNER |

### 4.2 Business data

| Feed | Grain | Key | Core fields | Classes |
| --- | --- | --- | --- | --- |
| Policy | one policy version | policy\_id\*, version | entity\*, product node\*, start date\*, end date\*, issue date, channel, currency, cancellation date | status: ACTIVE, LAPSED, CANCELLED, EXPIRED, MATURED; policy type: INDIVIDUAL, GROUP |
| Coverage | one coverage on a policy version | policy\_id\*, coverage\_code\* | sum insured, deductible, limit, coverage start/end | coverage group per line (e.g. own damage, liability, theft) |
| Exposure | one risk unit per period | policy\_id\*, coverage\_code, period\* | earned exposure\* (unit-years), exposure base (vehicle-year, sum insured, payroll), rating factors | exposure base type |
| Premium | one premium transaction | transaction\_id\* | policy\*, coverage, booking date\*, effective date\*, amount\*, currency\*, transaction type\* | WRITTEN, ENDORSEMENT, CANCELLATION, REFUND, INSTALMENT\_DUE, INSTALMENT\_PAID; COMMISSION; TAX\_OR\_LEVY |
| Claim | one claim (header) | claim\_id\* | policy, coverage, entity\*, line\*, occurrence date\*, report date\*, registration date, close date, reopen date, cause, event code, litigation flag, currency\* | status: OPEN, CLOSED, CLOSED\_NIL, REOPENED, LITIGATED; size class: ATTRITIONAL, LARGE, CATASTROPHE |
| Claim transaction | one money movement on a claim | transaction\_id\* | claim\_id\*, booking date\*, amount\*, currency\*, transaction type\* | PAYMENT, CASE\_RESERVE\_SET, CASE\_RESERVE\_CHANGE, EXPENSE\_ALLOCATED, RECOVERY\_SUBROGATION, RECOVERY\_SALVAGE, RECOVERY\_OTHER |
| Claim snapshot | one claim at one valuation date | claim\_id\*, valuation date\* | cumulative paid\*, case reserve\*, status\*, counts | as claim status |
| Reinsurance treaty | one treaty or layer | treaty\_id\* | type\*, inception\*, expiry\*, line scope, share or retention, limit, priority, reinstatements, commission | QUOTA\_SHARE, SURPLUS, EXCESS\_OF\_LOSS, STOP\_LOSS, FACULTATIVE |
| Reinsurance transaction | one ceded movement | transaction\_id\* | treaty\*, claim or policy, booking date\*, amount\*, type\* | CEDED\_PREMIUM, CEDED\_CLAIM\_PAID, CEDED\_CASE\_RESERVE, RI\_COMMISSION, REINSTATEMENT\_PREMIUM |
| Expense | one expense booking | transaction\_id\* | entity\*, line, period\*, amount\*, expense type\* | ACQUISITION, ADMINISTRATION, CLAIMS\_HANDLING\_UNALLOCATED, INVESTMENT, OTHER |

### 4.3 Finance and market data

| Feed | Grain | Key | Core fields | Classes |
| --- | --- | --- | --- | --- |
| Trial balance (ledger) | one account per entity per period | entity\*, account\*, period\* | opening, debit, credit, closing balance\*, currency | account class mapped to a measure: PREMIUM, CLAIMS\_PAID, OUTSTANDING, UPR, COMMISSION, EXPENSE, RI, INVESTMENT, OTHER |
| Market series | one value per series per date | series\_id\*, date\* | value\*, unit, source | FX\_RATE (pair, type: SPOT, PERIOD\_AVERAGE, PERIOD\_END), PRICE\_INDEX (CPI, PPI, wage, sector-specific), INTEREST\_RATE (tenor), YIELD\_CURVE |

### 4.4 Life and pension data

| Feed | Grain | Key | Core fields | Classes |
| --- | --- | --- | --- | --- |
| In-force | one contract at one valuation date | contract\_id\*, valuation date\* | product\*, entry date\*, age band\*, term, sum assured or fund value, premium frequency, rating factors | contract status: IN\_FORCE, PAID\_UP, LAPSED, SURRENDERED, MATURED, DEATH\_CLAIM, TRANSFERRED\_OUT |
| Life event | one decrement or movement | event\_id\* | contract\*, event date\*, event type\*, amount | DEATH, DISABILITY, SURRENDER, PARTIAL\_WITHDRAWAL, LAPSE, MATURITY, ANNUITY\_START, TRANSFER\_IN, TRANSFER\_OUT, REINSTATEMENT |
| Contribution and fund flow | one flow | flow\_id\* | contract\*, date\*, amount\*, flow type\*, fund code | CONTRIBUTION, EMPLOYER\_CONTRIBUTION, STATE\_CONTRIBUTION, FEE, BENEFIT\_PAYMENT, FUND\_SWITCH |

Four rules apply to the canonical concepts, whatever the input looked like. Money is always stored in its original currency with its currency code. Dates are dates, never text. Codes and identifiers are text, never numbers, so leading zeros survive. Derived fields such as quarters, development lags and year-month labels are recomputed by the platform and never trusted from the source.

Personal data is never needed. Age is used only as an age band, and sex only as an optional, aggregated rating factor that is off by default. Names, national identity numbers, customer numbers, addresses and phone numbers are recognised and dropped on load.

## 5. Canonical model

Everything the platform computes comes from two kinds of facts: **transactions** (dated movements of money or status) and **snapshots** (the state of an object at a valuation date). Either kind is accepted. Snapshots are rebuilt from transactions by accumulation, and transactions are rebuilt from consecutive snapshots by differencing. When both are supplied, the platform checks that they agree and reports every difference.

### 5.1 Time axes

Each fact carries up to five dates. Analyses choose which axis defines the origin and which defines development.

| Axis | Meaning | Used for |
| --- | --- | --- |
| Occurrence (accident) date | when the loss happened | accident-year triangles, frequency |
| Underwriting date | when the policy incepted | underwriting-year triangles, pricing cohorts |
| Report date | when the insurer learned of the claim | reporting delay, IBNR versus IBNER split |
| Booking (accounting) date | when the movement was recorded | calendar-period totals, ledger reconciliation |
| Valuation date | the as-known-at date of a snapshot | as-of reproduction of any past view |

The valuation axis is what makes results reproducible: any triangle, ratio or report can be rebuilt exactly as it looked on a past valuation date, using only facts booked on or before it.

### 5.2 Development and triangles

For an origin period i and a development period j, with period length p, development lag is measured in whole periods from the start of the origin period. A triangle cell is the aggregate of a measure over all facts in origin i with lag j:

```latex
X_{i,j} = \sum_{k \in \mathcal{F}} x_k \, \mathbf{1}\{\mathrm{origin}(k)=i,\ \mathrm{lag}(k)=j\}, \qquad C_{i,j} = \sum_{l \le j} X_{i,l}
```

X is the incremental triangle and C the cumulative one. The same definition yields paid, incurred (paid plus case reserve), reported counts, closed counts, recoveries, ceded and net triangles, by changing the measure x and the fact set F. Origin and development periods can each be month, quarter or year, independently.

### 5.3 Bases

Every money fact is tagged on three independent bases, so one engine serves every view:

- **Reinsurance basis:** GROSS, CEDED, NET (net = gross minus ceded).
- **Currency basis:** ORIGINAL, FUNCTIONAL, REPORTING.
- **Value basis:** NOMINAL, INFLATION\_ADJUSTED (to a stated value date), DISCOUNTED (at a stated curve).

Recoveries are kept as their own transaction types and shown both separately and netted, because subrogation and salvage behave very differently from payments in timing and size.

## 6. Data recognition and understanding

Phase 1 stands or falls on this layer: the user drops in files with any layout and any column names, and the platform works out what they are. Recognition is deterministic and explainable; a learned model may only suggest, and a person confirms.

### 6.1 Reading

Accepted inputs are tables: spreadsheets (each sheet), delimited text and columnar files. The reader finds the header row (first row whose cells are mostly distinct text above rows of typed values), ignores title and note rows, unmerges cells, and records file name, sheet, row number and a content fingerprint for every row, so each later number can point back to its source row.

### 6.2 Input shapes and concept detection

No layout is assumed. The reader first identifies the shape of each table, then splits it into the canonical concepts of section 4.

| Shape | Typical example | How it is handled |
| --- | --- | --- |
| Event rows | one row per payment or reserve movement | read as transactions |
| Entity snapshot | one row per claim or policy with cumulative paid and outstanding at a date | read as snapshots; transactions rebuilt by differencing between valuation dates |
| Periodic cumulative files | one file per partner per month, each a cumulative extract | each file becomes a snapshot set; the valuation date comes from a column, the file or sheet name, or the user |
| Wide combined extract | policy, claim and payment attributes on the same row, repeated across rows | split into policy, claim and transaction concepts; repeated attributes de-duplicated, conflicts reported |
| Pivoted periods | months or development periods as columns | unpivoted into rows |
| Pre-aggregated tables | triangles or totals by period | accepted as aggregate inputs; analyses needing claim-level detail are marked unavailable |

Three questions are answered for every table, each with its evidence shown to the user: which concepts its columns belong to; whether its money columns are incremental or cumulative (checked through monotonicity across valuation dates and agreement with any transaction rows); and what its grain and valuation date are.

Partner, company, channel and segment are dimensions found in the data, never a fixed file structure. When files overlap, for example the same claim in two cumulative extracts, the latest valuation wins for snapshots and the overlap is listed in the quality report.

### 6.3 Column mapping in five layers

1. **Normalise:** lower case with Turkish-aware folding (I, İ, ı, i), remove accents, punctuation and repeated spaces. STATUSON and Statü Son become the same token.
2. **Dictionary:** a bilingual alias table (Turkish and English, common abbreviations, known misspellings) maps tokens to canonical fields.
3. **Fuzzy match:** string similarity against canonical names and aliases, with a threshold.
4. **Value profile:** type, format, range, cardinality and distribution confirm or reject a candidate. A column of 11-digit numbers is an identity number and is dropped; a column of three-letter codes from ISO 4217 is a currency.
5. **Suggestion model (optional):** a classifier trained on synthetic and confirmed mappings ranks candidates when layers 1 to 4 are unsure.

The user confirms the mapping on one screen. The confirmed mapping is saved as a **mapping profile**: a small data file that is reused automatically the next time the same layout appears and that anyone can read and edit.

### 6.4 Value recognition

Categorical values are mapped to canonical classes in the same way. Status texts map to claim status, transaction types to section 4 classes, entity names to entity ids. Any value that cannot be mapped goes to an explicit UNMAPPED class and is listed, never dropped silently.

### 6.5 Data quality report

The quality report is the first page the user sees after loading. It scores each feed and each field on six dimensions:

| Dimension | Example checks |
| --- | --- |
| Completeness | share of empty required fields; missing periods in a monthly series |
| Validity | dates in range, currency codes in ISO 4217, amounts numeric, codes in the class list |
| Consistency | occurrence ≤ report ≤ payment ≤ close; paid never decreasing in snapshots; snapshot equals accumulated transactions |
| Uniqueness | duplicate transaction ids; identical rows across files |
| Reasonableness | negative payments without a recovery type; reserve jumps beyond a robust threshold; outliers by robust z-score |
| Coverage | which feeds and which time ranges are present, so the user knows what each analysis can use |

Every finding has a severity (INFO, WARNING, BLOCKING), a count, examples with source row references, and its effect on the analyses. BLOCKING findings stop only the analyses that depend on the affected field.

## 7. Money and time conventions

These conventions are fixed defaults that the user may override per run. Every override is written into the run manifest (section 12).

### 7.1 Currency conversion

Decision: keep every amount in its original currency, and convert only when a view needs it, using the rate type that matches the nature of the amount.

| Amount type | Rate | Reason |
| --- | --- | --- |
| Flows (payments, premiums, recoveries, expenses) | rate on the booking date; period-average rate when daily rates are missing | a flow happened at that moment's value |
| Stocks (case reserves, unearned premium, balances) | period-end rate of the valuation date | a stock is valued at the reporting date |
| Development analysis (triangles, factors) | one constant rate for all cells, by default the latest valuation date's rate | stops exchange-rate moves from looking like claims development |

Rates come from the market series feed. With no feed loaded, foreign-currency amounts stay in original currency and are reported separately rather than converted with an invented rate. A missing daily rate takes the nearest earlier business day and is flagged.

### 7.2 Inflation

In high-inflation markets, nominal development factors carry past inflation, so a chain ladder on nominal data silently extrapolates it. The platform therefore offers three value bases.

- **Nominal:** amounts as booked.
- **Inflation-adjusted:** each incremental amount restated to a common value date with a chosen price index. Default index: the consumer price index of the reporting currency; the user may choose a producer, wage or sector-specific index.
- **Discounted:** future cash flows discounted at a chosen yield curve (phase 2).

```latex
x^{\mathrm{adj}}_k = x_k \cdot \frac{I(t_{\mathrm{value}})}{I(t_k)}
```

Projections made on the adjusted basis are re-inflated with an explicit future inflation assumption to give nominal ultimates. The assumption is shown in the report next to the result.

### 7.3 Gross, ceded and net

Net always equals gross minus ceded, computed at the finest grain available. When ceded amounts arrive only at treaty level, they are allocated: proportional treaties by share, excess-of-loss layers by applying the layer terms to individual claims where claim-level data exists, otherwise at the aggregate level with a disclosed approximation.

### 7.4 Periods, signs and rounding

- Default period is the calendar month; fiscal year start and the valuation cut-off date are settings.
- Signs follow the insurer's view: premiums and payments are positive; cancellations and recoveries are negative contributions to their measures; net views add them.
- Calculations use full precision. Rounding happens only in presentation, half away from zero. Totals are computed from unrounded values, and the report says so where displayed parts do not add up.

## 8. Measures catalogue

A measure is a named, versioned formula with a grain and a list of required fields. Every number in the report is a measure or a method output; there are no ad hoc calculations. All measures exist on gross, ceded and net bases and any currency and value basis, where the inputs allow.

### 8.1 Catalogue

| ID | Measure | Definition | Needs |
| --- | --- | --- | --- |
| PR01 | Written premium | sum of WRITTEN + ENDORSEMENT + CANCELLATION + REFUND | Premium |
| PR02 | Earned premium | written premium spread over each policy's cover period (pro rata temporis by default) | Premium, Policy dates |
| PR03 | Unearned premium | written minus earned to date, at the valuation date | Premium, Policy dates |
| PR04 | Cancellation rate | cancelled premium / written premium | Premium |
| PR05 | Retention ratio | net written / gross written | Premium, RI transactions |
| PR06 | Average premium | earned premium / earned exposure | Premium, Exposure |
| CL01 | Paid | sum of PAYMENT | Claim transactions or snapshots |
| CL02 | Case reserve | outstanding case estimate at valuation date | Claim transactions or snapshots |
| CL03 | Incurred (reported) | paid + case reserve | as CL01, CL02 |
| CL04 | Reported, open, closed, nil-closed, reopened counts | counts by status at valuation date | Claim |
| CL05 | Frequency | reported count / earned exposure | Claim, Exposure |
| CL06 | Severity | incurred / reported count (attritional and large shown apart) | Claim, transactions |
| CL07 | Reporting delay | report date − occurrence date: mean, median, percentiles | Claim |
| CL08 | Settlement time | close date − report date; survival curve for open claims | Claim |
| CL09 | Settlement rate | closed in period / (open at start + reported in period) | Claim |
| CL10 | Paid-to-incurred ratio | paid / incurred by origin and lag | transactions |
| CL11 | Case reserve run-off | later paid + remaining reserve versus earlier reserve, per claim cohort | snapshots at two dates |
| CL12 | Large-loss share | incurred of LARGE and CATASTROPHE claims / total incurred | Claim |
| RC01 | Subrogation ratio | subrogation recovered / paid | transactions |
| RC02 | Salvage ratio | salvage recovered / paid | transactions |
| RI01 | Cession ratio | ceded / gross, for premium and for claims | RI transactions |
| RI02 | Reinsurance result | ceded claims + RI commission − ceded premium | RI transactions |
| EX01 | Commission ratio | acquisition commission / earned premium | Premium, Expense |
| EX02 | Expense ratio | (acquisition + administration) / earned premium | Expense, Premium |
| EX03 | Claims-handling ratio | (allocated + unallocated claims expense) / paid | Expense, transactions |
| RT01 | Loss ratio (paid, incurred, ultimate) | claims measure / earned premium | Premium, Claims |
| RT02 | Combined ratio | ultimate loss ratio + expense ratio + commission ratio | as above |
| RS01 | Development factors | C(i, j+1) / C(i, j), plus weighted and selected factors | triangles |
| RS02 | Ultimate, IBNR, IBNER | per method in section 9 (indicative) | triangles, premium for BF |
| RS03 | Reserve range and risk measures | standard error, percentiles, VaR and TVaR of the reserve distribution | stochastic method |
| AE01 | Actual versus expected | actual movement in a period / movement expected by the last selection | two valuations |
| LF01 | Lapse and surrender rate | events / exposed-to-risk, by duration and product | In-force, Life events |
| LF02 | Mortality and morbidity actual/expected | actual deaths / expected deaths from a reference table | In-force, Life events |
| LF03 | Persistency | share of contracts still in force after n years | In-force |
| LF04 | Net fund flow | contributions − benefits − transfers out + transfers in | Fund flows |
| FN01 | Ledger reconciliation gap | platform measure − mapped ledger balance, per account class and period | Ledger + matching feed |
| DQ01 | Data quality score | weighted pass rate of the section 6.5 checks | any |

### 8.2 Specification template

Each measure has one specification file with: ID and version; name in English and Turkish; definition in one sentence; formula; numerator and denominator; grain and allowed breakdowns; bases supported; required and optional fields; edge cases (zero denominator, negative values, missing periods); interpretation and typical range; the test that proves it; change log.

## 9. Methods library

Methods are ranked by usefulness to a typical actuarial team: tier A answers the questions asked every month, tier B adds depth and uncertainty, tier C adds data science challengers and specialist studies. Phase 1 ships tier A only.

### 9.1 Tier A — phase 1

| Method | Answers | Key assumption | Check against |
| --- | --- | --- | --- |
| Descriptive profiling and trends | what is in the data and how it moves | none | synthetic ground truth |
| Triangle construction (paid, incurred, counts; any origin and lag period) | how claims develop | section 5.2 definitions | hand-computed fixtures |
| Chain ladder (volume-weighted, simple and recent-diagonal averages, outlier exclusion) | ultimate and IBNR | stable development pattern | published benchmark triangles |
| Bornhuetter–Ferguson | ultimate for immature origin periods | a prior loss ratio is credible | benchmark triangles |
| Cape Cod | prior loss ratio estimated from the data | stable loss ratio across origins | benchmark triangles |
| Expected loss ratio | ultimate for the newest periods | prior loss ratio | trivial fixture |
| Mack model | standard error of chain-ladder reserves | Mack's three assumptions | Mack (1993) published results |
| Loss, expense and combined ratios with trend | profitability | earned premium is right | synthetic ground truth |
| Inflation-adjusted chain ladder | development net of price inflation | chosen index reflects claims inflation | synthetic ground truth |
| Robust anomaly flags (robust z-score, isolation forest) | which payments, reserves or files look wrong | anomalies are rare | injected anomalies in synthetic data |

### 9.2 Tier B — phase 2

| Method | Answers |
| --- | --- |
| Over-dispersed Poisson bootstrap | full reserve distribution, percentiles, VaR and TVaR |
| Munich chain ladder | consistent paid and incurred projections |
| Benktander and credibility-weighted blends | a principled mix of chain ladder and BF |
| Tail factor fitting (inverse power, exponential decay) | development beyond the triangle |
| Separation method | calendar-year (inflation) effects versus development |
| Frequency–severity projection | ultimate as count × severity |
| Severity distribution fitting (lognormal, gamma, Weibull, Pareto) with goodness of fit | size of loss and limits |
| Extreme value analysis (peaks over threshold, generalised Pareto) | large-loss threshold and tail |
| Survival analysis (Kaplan–Meier, Cox) | settlement time, lapse and persistency |
| Life experience studies with credibility | mortality, morbidity and lapse actual/expected |
| Reinsurance what-if (quota share, surplus, excess-of-loss layers on claims) | ceded and net under alternative programmes |
| Back-testing of past selections | how good were previous reserve estimates |

### 9.3 Tier C — phase 2 and later

| Method | Answers |
| --- | --- |
| Generalised linear models (Poisson, gamma, Tweedie) | which rating factors drive frequency and severity |
| Individual claim reserving with gradient-boosted trees | a claim-level challenger to triangle methods |
| Large-loss early warning (classification on early claim features) | which new claims will become large |
| Settlement-time prediction | when open claims will close |
| Count and premium forecasting (exponential smoothing, state space) | next periods' volumes |
| Portfolio segmentation (clustering) | homogeneous groups for analysis |
| Explainability (feature attributions, partial dependence) | why a model says what it says |

Data science models enter only as **challengers**: they run beside a tier A champion on the same data, and the report shows both with their back-test error. A challenger never silently replaces a classical method.

### 9.4 Specification template

Each method has one specification file with: purpose; assumptions and how to test them; inputs and parameters with defaults; the algorithm as formulas; outputs; diagnostics (residual plots, factor stability, assumption tests); failure modes and what the platform does in each; validation evidence; references.

## 10. Analysis modules

A module is a bundle of measures and methods that answers one business question. Each module declares what it needs; the platform runs every module whose required feeds are present and lists the rest with the reason they did not run.

| ID | Module | Question it answers | Required | Improves with | Phase |
| --- | --- | --- | --- | --- | --- |
| M01 | Data understanding | What did I load, and can I trust it? | any file | all | 1 |
| M02 | Portfolio and premium | How big is the book, where does it grow or shrink? | Premium or Policy | Exposure, Distribution | 1 |
| M03 | Claims experience | How many claims, how large, how fast? | Claim + claim transactions or snapshots | Exposure | 1 |
| M04 | Reserving (indicative) | What will claims finally cost, and how sure are we? | claim transactions or snapshots | Premium (for BF and Cape Cod), Market series (inflation) | 1 |
| M05 | Profitability | Do we make money by line and period? | Premium + claims | Expense, RI | 1 |
| M06 | Anomalies and large losses | What looks wrong or unusual? | claim transactions | Claim, Policy | 1 |
| M07 | Recoveries | How much do subrogation and salvage bring back, and when? | recovery transactions | Claim | 2 |
| M08 | Reinsurance | What is ceded, what is net, what would another programme do? | RI treaty + RI transactions | claim-level data | 2 |
| M09 | Expenses | What does it cost to write and handle business? | Expense | Premium, claims | 2 |
| M10 | Ledger reconciliation | Do actuarial figures agree with the books? | Ledger + the matching feed | account mapping profile | 2 |
| M11 | Life and pension experience | Do deaths, lapses and surrenders behave as expected? | In-force + Life events | reference tables | 2 |
| M12 | Uncertainty and risk | How wide is the reserve range; what are VaR and TVaR? | M04 inputs | — | 2 |
| M13 | Model challengers | Would a data science model do better? | M03/M04 inputs at claim level | Policy, Exposure | 2 |
| M14 | Governance packs | Contracts, store, closing, controls, roles | per pack | — | 3 |

Modules never consolidate segments by default. Non-life, life, pension and health are analysed and reported separately; a combined view exists only where a measure is meaningful across them (premium volume, expense) and is marked as such.

## 11. Executive report

The report is the product: the moment the data is loaded and the mapping confirmed, the platform writes one self-contained report that a manager can read in ten minutes and an actuary can audit in an hour. It is produced as an interactive single-file page and as a printable document with identical numbers.

**Structure, in reading order:**

1. **Cover:** entity, segments, valuation date, bases chosen (gross or net, currency, value basis), run id.
2. **Key findings:** five to eight sentences generated from fixed rules, each with its number and a link to the evidence (e.g. “Incurred loss ratio for motor rose from 68% to 74%; two thirds of the rise comes from three large claims.”). Wording is template-based and deterministic, never free-generated.
3. **At a glance:** headline tiles (premium, claims, ratios, reserve estimate with range, data quality score), each with the change against the previous period.
4. **One page per module that ran:** its charts, its tables and its findings.
5. **Reserving:** triangles as heatmaps, development factors with the selection, ultimates by method side by side, Mack range, diagnostics.
6. **What did not run and why:** modules skipped for missing feeds, with what to load to enable them.
7. **Data quality appendix:** the section 6.5 report.
8. **Methods and assumptions appendix:** each method used, its version, parameters and assumptions, in plain language.
9. **Reproducibility appendix:** the run manifest (section 12).

**Rules for every page.** Each figure carries a footnote with its measure or method ID, version and basis. Every analytic page carries the label “indicative — not an official reserve or price”. Charts follow one visual system: the same colour always means the same segment or basis, ranges are drawn as ranges, and no chart has more than one message.

The user can change bases, periods and segments in the interactive page; each change is a new run with its own manifest, so a printed page is always reproducible.

## 12. Reproducibility and audit trail in phase 1

Phase 1 has no governed store, but every run is still fully auditable through one artefact: the **run manifest**, written next to every report.

| Manifest entry | Content |
| --- | --- |
| Run id | unique id derived from the fingerprints below |
| Inputs | each file's name, size and SHA-256 fingerprint; sheets and row counts used |
| Mapping profiles | id, version and fingerprint of each profile applied, including user confirmations |
| Configuration | every setting and every override against the defaults (section 7) |
| Methods and measures | ID and version of each one used, with parameters and selections |
| Assumptions | the assumptions register entries in force (prior loss ratios, inflation index and future inflation, tail factors) |
| Randomness | seeds of every stochastic step |
| Software | platform version and the version of each component |
| Outputs | fingerprint of each output file |

Two rules make the manifest sufficient. Rerunning a manifest on the same inputs must reproduce every output fingerprint exactly; a mismatch is a defect. And every number in the report links to its row in a **lineage table** that records the source rows and the measure or method that produced it.

User judgement is data too. Selected development factors, prior loss ratios, excluded outliers and overridden mappings go into an **assumptions register** with who chose them, when, why, and the alternative. This register is what an auditor reads first, and it is the bridge to the phase 3 governance packs.

## 13. Synthetic data and validation

The synthetic data generator is a first-class component, built before the analytics. Because it knows the true answer, the platform can prove that every method recovers it.

### 13.1 Generator

The generator simulates a whole insurer from a scenario file, so every run is reproducible from its seed:

1. **Portfolio:** policies by product and channel with start dates, terms, sums insured, rating factors and cancellations; exposure follows.
2. **Premium:** written, instalments, endorsements, refunds and commissions from the policies.
3. **Claims:** occurrences from a Poisson process on exposure; reporting delays and settlement times from chosen distributions; severities from lognormal or gamma bodies with a Pareto tail; payment patterns; case reserves set and revised with a controllable bias; reopenings; nil closures.
4. **Recoveries and reinsurance:** subrogation and salvage with their own timing; treaties applied to produce ceded amounts.
5. **Expenses and ledger:** expense bookings and a trial balance consistent with the transactions.
6. **Market series:** exchange rates as random walks, price indices with a chosen inflation path, a yield curve.
7. **Life and pension:** in-force contracts with deaths from a reference mortality table, lapses, surrenders, maturities, contributions and fund flows.
8. **Messiness layer:** renamed and misspelt headers, Turkish and English column names, extra title rows, mixed date formats, duplicates, missing feeds, wide combined extracts, cumulative files per partner and month, months as columns, injected anomalies, personal-data columns to be dropped.

The scenario library covers at least: clean baseline; messy layout; missing feeds; high inflation; large-loss shock; reserve-strengthening change; reinsurance programme change; currency devaluation.

### 13.2 Validation layers

| Layer | What it proves |
| --- | --- |
| Rule tests | each measure and method matches its specification on small hand-computed fixtures |
| Ground-truth tests | on synthetic data, estimates converge to the simulated truth within stated tolerances |
| Benchmark tests | chain ladder and Mack reproduce published results on public benchmark triangles |
| Property tests | invariants hold on random inputs: net = gross − ceded; snapshot = accumulated transactions; cumulative triangles never lose amounts; results do not depend on row order |
| Recognition tests | each messy scenario maps to the clean canonical data |
| Golden reports | a fixed scenario produces a fixed report fingerprint; any change needs a reviewed reason |
| Performance tests | load-to-report time on the largest scenario stays within budget |

Numerical tolerance is set per test and written in its specification; there is no global tolerance. A failing benchmark blocks a release.

## 14. Engineering blueprint

The blueprint is written as components with data contracts between them. Any implementation (a program, a spreadsheet, a team with paper) is correct if each component turns the specified input tables into the specified output tables.

### 14.1 Components

| Component | Input | Output | Rule |
| --- | --- | --- | --- |
| Reader | files | raw tables with source row references | never changes a value |
| Recogniser | raw tables, alias dictionary, mapping profiles | proposed feed and column mappings with confidence | deterministic; suggestions only from the model |
| Canonicaliser | raw tables, confirmed mapping profile | canonical feeds (section 4) | drops personal data; recomputes derived fields |
| Quality profiler | canonical feeds | quality findings and scores | read only |
| Converter | canonical feeds, market series, settings | amounts on the requested bases | section 7 conventions |
| Structure builder | converted feeds | triangles, exposure tables, cohorts, snapshots | section 5 definitions |
| Measure engine | structures, measure specs | measure values with lineage | one function per measure spec |
| Method engine | structures, method specs, parameters | estimates, ranges, diagnostics | one function per method spec; seeded |
| Module runner | available feeds, module definitions | which modules run and why others did not | section 10 |
| Narrator | measure and method outputs, finding rules | key-finding sentences | template rules only |
| Reporter | all outputs, report layout | report page and printable document | identical numbers in both |
| Manifest writer | everything above | run manifest, lineage table | section 12 |

Every component is a pure transformation: no hidden state, no network access, no writes outside the run folder. Methods and measures are registered from their specification files, so adding one never touches the core.

### 14.2 Reference implementation (decision)

The first implementation is in Python, because it has mature, well-tested numerical, statistical and machine-learning libraries and is the common language of actuarial data science, which matters for an open-source portfolio.

- **Core:** a library with no user interface, usable from scripts and notebooks.
- **Command line:** load, map, run and report in one command, for automation and tests.
- **Desktop app:** a local application that opens in the browser on the user's own machine, packaged as a single downloadable executable. A browser interface is the easiest to build, to keep consistent with the interactive report, and to port later.
- **Report:** a self-contained interactive page plus a printable document generated from the same page.
- **Data engine:** a columnar dataframe library for transformations and an embedded analytical database for large joins and aggregations; nothing needs a server.

The specifications stay the source of truth. An Excel or C++ implementation would use the same specification files and pass the same fixture and benchmark tests.

### 14.3 Performance budget

On an ordinary laptop, the largest scenario (ten years, about one million claim transactions) loads, maps and reports in under two minutes; changing a basis or a segment in the report takes under five seconds. Budgets are measured by the performance tests, never assumed.

## 15. Clean code and repository culture

The repository is organised so that the specification is read first and the code second.

```
spec/
  data/        one file per feed: fields, types, classes, rules (section 4)
  measures/    one file per measure (section 8)
  methods/     one file per method (section 9)
  modules/     one file per module (section 10)
  conventions/ currency, inflation, bases, periods, rounding (section 7)
  aliases/     bilingual column and value dictionary (section 6)
src/           implementation; folder names mirror spec/
tests/         fixtures, benchmarks, ground-truth and property tests, mirroring spec/
synthetic/     generator and scenario files (section 13)
examples/      sample datasets and the reports they produce
docs/          user guide, method notes, decision records, glossary
```

**Rules in force:**

- **One rule, one specification.** A business rule lives in exactly one spec file; code and tests reference its ID. Changing a rule means changing its spec first.
- **Names come from the domain.** earned\_premium, case\_reserve, development\_lag; no abbreviations a newcomer must guess; English in code, a Turkish label in the glossary.
- **Small pure functions.** One function does one transformation, takes tables in and returns tables out, and has no side effects.
- **No magic numbers.** Every threshold, tolerance and default lives in configuration with a comment on why.
- **Tests next to rules.** A spec without a test is not done; a test names the spec ID it proves.
- **Decision records.** Every significant choice gets a short numbered record: context, options, decision, consequences. Records are never edited, only superseded.
- **Versioning.** Semantic versions for the platform; every spec carries its own version; the changelog is written for users.
- **Definition of done:** spec written, implementation, tests green, docs updated, example report regenerated, decision record if a choice was made.
- **Automated gates on every change:** formatting, static analysis, type checks, the full test suite, a secret and personal-data scan of the repository, and the golden report comparison.
- **Reviews.** Every change goes through a pull request with a description of what changed and why, even for a single maintainer.

## 16. Roadmap

```
Phase 0  Foundations            -> G0 Ready to build
Phase 1a Understand             -> G1 Data understood
Phase 1b Analyse and report     -> G2 Numbers proven
Phase 1c Public release v1.0    -> G3 Usable by a stranger
Phase 2  Deepen                 -> G4 Core proven in use
Phase 3  Govern (optional packs)
```

The plan is gate-based: a phase starts when the previous gate's criteria are met, not on a date. Phase 1 is split in three so that the first visible result, a quality report on any file, arrives before the analytics.

## 17. Open source and portfolio

The project is a personal, open-source portfolio work. That shapes four choices.

- **Licence:** Apache 2.0, a permissive licence with an explicit patent grant, common in data science projects and easy for companies to adopt.
- **Clean origin:** built on personal time and equipment, from public literature and synthetic data only. No employer data, file layouts, names, code or internal methods enter the repository. Before publishing, check the employment contract's intellectual-property clause; this blueprint is not legal advice.
- **Showcase:** the repository's front page shows a sample executive report from a synthetic scenario, the benchmark reproduction results, and a two-minute path from download to first report.
- **Method notes:** each tier A and B method gets a short public note (theory, assumptions, a worked example on synthetic data). These notes are what shows actuarial depth to a reader who never runs the code.

Adoption at a workplace later is a matter of loading that company's files and confirming the mappings; nothing company-specific needs to be in the open project.

## 18. Decisions and open questions

### 18.1 Decisions taken

| ID | Decision | Reason |
| --- | --- | --- |
| D01 | The platform is analytics-first; governance is a phase 3 optional pack | governance depends on each company's regulation and culture; analytics is universal |
| D02 | Specifications are language-neutral and are the source of truth | the design must survive any implementation choice |
| D03 | No input layout is required; files are split into canonical concepts, and modules degrade with a stated reason | real datasets are never complete |
| D04 | Canonical model = transactions + snapshots on five time axes | one engine yields every triangle, ratio and as-of view |
| D05 | Original currency is always kept; flows at booking-date rate, stocks at period-end rate, constant rate for development | correct valuation without exchange-rate noise in development |
| D06 | Inflation-adjusted basis with a user-chosen index, default consumer price index | nominal factors carry past inflation |
| D07 | Gross, ceded and net on every measure where inputs allow | the user chooses the view |
| D08 | Recognition is deterministic; learned models only suggest | explainability and auditability |
| D09 | Data science models enter as challengers beside a classical champion | no silent replacement of transparent methods |
| D10 | All outputs are labelled indicative | the platform is not a system of record |
| D11 | No personal data is ever required; identifying columns are dropped on load | privacy by design |
| D12 | Python reference implementation; local browser-based app packaged as an executable; self-contained report | best libraries, easiest to package and to match the report |
| D13 | The synthetic generator is built before the analytics | methods are proven against known truth |
| D14 | Apache 2.0 licence | permissive, patent grant, easy adoption |

### 18.2 Open questions

- Working name of the project.
- Default reference mortality and lapse tables for the life module that can be redistributed openly.
- Whether phase 1 should include a minimal health segment or leave it to phase 2.
- The default large-loss threshold rule: fixed amount, percentile, or extreme-value based.
- Whether to publish method notes as a documentation site from the start or after the first release.

## 19. Glossary

| English | Türkçe | Note |
| --- | --- | --- |
| Non-life / Life / Pension | Elementer / Hayat / Bireysel emeklilik | segments, never consolidated by default |
| Claim | Hasar (dosya) |  |
| Occurrence (accident) date | Hasar tarihi | origin axis for accident-year triangles |
| Report date | İhbar tarihi |  |
| Payment date | Ödeme tarihi |  |
| Paid claims | Ödenen hasar |  |
| Case reserve, outstanding | Muallak hasar | per-claim estimate |
| Incurred | Gerçekleşen hasar | paid + case reserve |
| IBNR | Gerçekleşmiş ancak rapor edilmemiş hasar |  |
| Ultimate loss | Nihai hasar |  |
| Development triangle / factor | Gelişim üçgeni / faktörü |  |
| Accident year / Underwriting year | Kaza yılı / Poliçe (tanzim) yılı |  |
| Written / Earned premium | Yazılan / Kazanılmış prim |  |
| Unearned premium reserve | Kazanılmamış primler karşılığı |  |
| Coverage / Sum insured / Deductible | Teminat / Sigorta bedeli / Muafiyet |  |
| Subrogation / Salvage | Rücû / Sovtaj |  |
| Reinsurance: quota share, surplus, excess of loss | Reasürans: kotpar, eksedan, hasar fazlası |  |
| Gross / Ceded / Net | Brüt / Devredilen / Net (saklı pay) |  |
| Commission / Expense | Komisyon / Gider |  |
| Loss ratio / Combined ratio | Hasar prim oranı / Bileşik oran |  |
| Trial balance | Mizan |  |
| Exchange rate / Consumer price index | Döviz kuru / Tüketici fiyat endeksi |  |
| Surrender / Lapse / Maturity / Death | İştira / İptal (prim ödememe) / Vade sonu / Vefat | life events |
| Exit / Contribution / Fund | Ayrılma / Katkı payı / Fon | pension terms |
| Exposure | Risk birimi (maruziyet) |  |
| Mapping profile | Eşleme profili | section 6.3 |
| Run manifest | Çalışma manifestosu | section 12 |

## 20. References

Compiled from memory as starting points for the method notes; verify editions and page numbers before citing.

- Bornhuetter, R. L. and Ferguson, R. E. (1972). The Actuary and IBNR. Proceedings of the Casualty Actuarial Society.
- Mack, T. (1993). Distribution-free calculation of the standard error of chain ladder reserve estimates. ASTIN Bulletin.
- England, P. D. and Verrall, R. J. (2002). Stochastic claims reserving in general insurance. British Actuarial Journal.
- Quarg, G. and Mack, T. (2004). Munich Chain Ladder. Blätter der DGVFM.
- Taylor, G. (2000). Loss Reserving: An Actuarial Perspective. Kluwer.
- Friedland, J. Estimating Unpaid Claims Using Basic Techniques. Casualty Actuarial Society.
- Wüthrich, M. V. and Merz, M. (2008). Stochastic Claims Reserving Methods in Insurance. Wiley.
- Wüthrich, M. V. and Merz, M. (2023). Statistical Foundations of Actuarial Learning and its Applications. Springer.
- Klugman, S. A., Panjer, H. H. and Willmot, G. E. Loss Models: From Data to Decisions. Wiley.
- Ohlsson, E. and Johansson, B. (2010). Non-Life Insurance Pricing with Generalized Linear Models. Springer.
- Bühlmann, H. and Gisler, A. (2005). A Course in Credibility Theory and its Applications. Springer.
- Open benchmark implementations to compare against: the ChainLadder package for R and the chainladder package for Python, which ship published benchmark triangles.
