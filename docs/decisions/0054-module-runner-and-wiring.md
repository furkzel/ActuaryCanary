# 0054 — Module runner, and premiums, policies and expenses in `canary run`

## Context
Until P09 `canary run` read claim valuations and claims, checked the other concepts for the quality report and ran the chain ladder. The owner asked that premiums, policies and expenses feed the analysis and that the run says which modules ran and why others did not.

## Decision
- Every sheet recognised as premiums, policies, expenses or market is read, listed in the manifest inputs and no longer in `tables_not_used`; their specs are recorded. The module specs and their measure specs are recorded for every run, because the set does not depend on the data.
- `modules.runner.run_modules` takes each module's status from the quality report (decision 0032): "unable" skips the module with the reason of its spec or of the blocking finding; "limited" marks the measures that read the blocked field as blocked. A module that is not unable computes every measure of its spec on the default views (`modules/views.py`) on the run's bases, or on the first basis the spec defines (with a note). It is `ran`, `limited` (some measure or method not available) or `skipped`. MT01 and MT02 count as built because the pipeline runs them first; the other methods are listed as not built.
- Results are a typed structure (`AnalysisResult` of `ModuleOutcome` of `MeasureResult`). The terminal shows a Modules table, the report a "Modules and measures" section, and `modules.json`, `measures.csv` and `lineage.csv` hold the same for machines.
- The chain ladder still runs next to a module that is marked unable (0032 stands).

## Consequences
- The report page grows by the section; figures and tables of the measures are a later item.
- When P08 plugs its port in, RS01 to RS03, AE01, RT02 and the ultimate ratio of RT01 appear without changes here.
