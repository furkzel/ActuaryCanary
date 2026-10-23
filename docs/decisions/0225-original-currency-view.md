# 0225 — The ORIGINAL currency view of a run (`--currency-view original`)

## Context
CV01 names three views: ORIGINAL, FUNCTIONAL and REPORTING. The engine already computed single measures in ORIGINAL, one row per currency, but a run could only be REPORTING. FUNCTIONAL is not defined well enough to compute: CV01 says only that it equals REPORTING in version 1.0 because no entity feed names a functional currency. The owner decided: add ORIGINAL only; FUNCTIONAL stays equal to REPORTING until CV01 defines it.

## Decision
- `RunSettings.currency_view` (REPORTING by default, ORIGINAL), `canary run --currency-view reporting|original`. It is part of the settings and so of the run id and the manifest (`bases.currency`, `currency_conversion` "none"). `functional` is refused with a message that says it equals reporting.
- **How a run keeps currencies apart.** After the feeds are read, every claim takes the currency of its valuations and every policy its own into its `line`: `MOTOR_OD [TRY]`, `MOTOR_OD [USD]`. Triangles, methods, anomaly flags and all measures then group by that line and never meet another currency. Every rate is 1 (`DevelopmentRates` identity, and the conversion target "orig." is the identity for the measure engine), so REPORTING-only measures (RT01, RT02, RS01–RS03, AE01) are right line by line. A claim of unknown currency keeps its line.
- **All-business views.** Measures that CV01 defines in ORIGINAL (PR01, PR04, PR05, RI01, RI02, EX01–EX03 and the amount measures) are asked in the ORIGINAL view, which gives one row per currency; the report shows one entry per currency.
- **Totals.** A segment whose lines are in more than one currency gets no segment tiles and no segment sentences of RP01; its lines stand on the reserving page. The page says "orig." where it names the reporting currency, and a cover row names the view.
- **Not built in this view:** the inflation-adjusted value basis (stops with a message) and the other value basis for MT07; premium booked in a currency other than its policy's is listed under its own currency; DV-MKT-07 is not evaluated, because no series is needed.
- CV01 1.2.0 says so.

## Consequences
- Baseline tiny in ORIGINAL: five lines, among them `PROPERTY [USD]` with one claim whose paid is 0.13 (dollars), not converted; `MOTOR_OD [TRY]` and `MOTOR_TPL [TRY]` have the numbers of the REPORTING run.
- Thin lines (a currency with a handful of claims) are shown as they are, with the usual thin-evidence diagnostics; the platform does not merge or hide them.
- Every run id changes once more through the new setting (all examples); the REPORTING numbers do not move.
