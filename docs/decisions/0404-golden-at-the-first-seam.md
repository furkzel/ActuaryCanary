# 0404 — Golden at the seam after stage 3 of F2a

## Context
Stages 1 to 3 of F2a built the treaty application (MT21), the CV09 allocation, the CV03 1.1.0 ceded fields and the premium side, and added the run setting `reinsurance` (record 0401: `index_clause`; 0403: `allocation_fallback`; the what-if fields of MT21). No module is wired yet, so the tiny baseline run computes nothing new.

## Decision
`just golden` ran once (2026-11-12) and the diff was read entry by entry. Every change has a cause:
- Parameter rows (both languages): six new rows `reinsurance.allocation_fallback` = aggregate, `reinsurance.index_clause` = payment_by_payment, `reinsurance.inuring_order` = CV09, `reinsurance.loss_view` = ultimate, `reinsurance.programme` = loaded, `reinsurance.simulate` = False. Cause: the new block of `RunSettings`.
- Run ids: English 7eaa8477d8aaab61 → 4c9ed560ad01f5b8, Turkish 89aab15f3692bf8e → 30a766e143fd5cbc. Cause: the settings enter the run id.
- Nothing else moved: no estimate, measure value, finding, label or spec version.

## Consequences
- The golden copies are renewed with these entries. The spec versions (CV03 1.1.0, CV09 0.3.0 and the drafts) are written in stage 5 with the module, so they move the golden then.
