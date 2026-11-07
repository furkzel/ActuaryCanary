# 0320 — The aliases of the interest rates move into AL01 and AL02

## Context
AL03 and AL04 hold the aliases of the planned concepts so that AL01, AL02 and the run id do not move before a concept is built (0242 and the note of AL03). The concept `interest_rates` is built by this item.

## Decision
- The seven column entries (curve_id, date, tenor_months, rate, rate_type, compounding, source) and the two value entries (rate_type, compounding) of `interest_rates` move from AL03 and AL04 into AL01 and AL02, which become 1.1.0. The `currency` entry of AL01 lists `interest_rates` as well, and the entry of AL03 no longer does (a concept field needs exactly one entry in the combined dictionary). AL03 and AL04 become 0.2.0 and stay planned.
- No alias token was added or changed; the tokens are those of P20.

## Consequences
- A workbook with these columns is recognised as `interest_rates` wherever it lies directly in the input folder. The generator keeps its feeds in `phase2/` (0242), so no folder of the repository changes by this alone. The defect named for P28 (an unknown workbook read as a known concept) is not touched.
- The versions of AL01 and AL02 are in every manifest, so the run ids move once.
