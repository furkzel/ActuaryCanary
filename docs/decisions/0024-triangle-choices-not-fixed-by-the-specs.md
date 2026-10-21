# 0024 — Triangle choices the specifications leave open

## Context
Building triangles from the canonical feeds needed a few rules that the specifications do not state in numbers. None changes a spec; each is chosen here so that it can be reviewed.

## Decision
- **Currencies without a rate.** Market data is not read yet, so only amounts in the reporting currency have a development rate (1). Amounts in any other currency, and rows whose currency is UNKNOWN (DV-CLV-03), are left out of the reporting-currency triangles at the valuation points where they are the claim's as-of row, and their as-of totals at the cut-off are shown per currency (CV01: no invented rate). On the tiny baseline this is one USD claim and one claim whose cut-off row has no currency.
- **Empty amounts.** A row with an empty paid_to_date (or, for incurred, an empty case_reserve) is treated as absent for that measure, so the claim's previous row carries forward (DV-CLV-02 "excluded from money measures", CL03).
- **Origin rows.** Every group shows the same origin periods: from the earliest origin of any claim in the run to the origin that contains the cut-off. An origin without claims is a row of zeros; chain ladder gives it a zero ultimate and flags it (MT02).
- **Claims without a usable origin.** A claim with a header but an empty origin date, or one after the cut-off, is left out of the triangles and listed (MT01, DV-CLM-07). A claim without a header uses its first-valuation origin and group UNKNOWN/UNKNOWN (decision 0008).
- **Valid currency** means three capital letters; no ISO 4217 list is in the toolchain. **Status and segment** match their classes exactly; value aliases (AL02) come with recognition.
- **Thin cells** are those with fewer than 5 reported claims (MT01 diagnostic), counted per group in the report.

## Consequences
- Once market data is converted, foreign claims join the triangles and the not-converted table empties; no other part of the path changes.
- Ground truth (baseline medium, quarterly development) matches cell by cell within 1e-12 after the injected faults' known effects; cells whose as-of row is a lowered paid_to_date cannot be restated and are not compared (66 of 880 cells, each with paid and incurred).
