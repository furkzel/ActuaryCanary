# 0050 — Measure engine, results, lineage and the port to the methods

## Context
P09 computes every version 1.0 measure from its spec and runs modules M01 to M06. The report will render the results, and the methods (P08) arrive in parallel. Measures must not import methods, and every value must say which rule and which rows produced it.

## Decision
- `measures.engine.run_measure(catalogue, inputs, measure_id, request)` reads the spec first: a breakdown or basis the spec does not define, a required field that is not loaded (named by concept and column) or a breakdown the spec allows but this version does not build is refused with the reason. Only then does the measure function run, and its own edge cases decide where a value is "not computed" (a null `value` with a `note`) or the measure is unavailable (the reason).
- A result (`MeasureResult`) holds the spec ID and version, the request (breakdowns, period, basis), a polars frame (breakdown columns, `value`, `numerator` and `denominator` of ratios, `note`), notes for the reader, and secondary tables (survival curve, claims carried forward).
- Lineage: every feed gets a `_ref` position; each value row carries `refs_<concept>` lists of the source rows behind it. `measures.csv` (every numeric column unrounded, with spec version and basis) and `lineage.csv` (file, sheet, row ranges per value) are written next to the report. Values read from triangles (CL10, AE01) point to the triangle cells instead of rows.
- Methods: measures reach method outputs only through `MethodsPort` (`measures/port.py`): the selection at a valuation date (selected ultimates and cumulative factors, for RT01, RT02 and AE01) and the tables of RS01 to RS03. `NoMethods` answers "not available" with the reason. P08 provides the real port; nothing in `measures/` imports `methods/`.
- RT01 and RT02 therefore show no ultimate ratio and no combined ratio until MT10 exists; the chain ladder is not substituted for the selection, because the spec names MT10.
- Breakdowns in this version: the spec's list minus `development_period` for CL01 to CL03 (the triangles are that view) and `entity` for CL10 and AE01 (triangles are built by segment and line). Group-bys keep their order, so reruns are byte-identical.

## Consequences
- A new measure is one function and one line in `engine.IMPLEMENTATIONS`; a new method reaches measures by implementing the port.
- `canary run` output files grow by `measures.csv`, `lineage.csv` and `modules.json`.
