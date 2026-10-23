# 0064 — Thin evidence: fewer than eight origin periods, confirmed

## Context
Record 0039 set the thin-evidence warning of the method diagnostics at fewer than 8 origin periods. The brief of P09b said "fewer than four" and also forbade changing thresholds, so the code was left at 8 and the question went to the owner (record 0059).

## Decision
Confirmed by the owner for P08b: the diagnostics warn of thin evidence when a triangle has fewer than **eight** origin periods, not four. `THIN_EVIDENCE_ORIGINS` stays 8. The code, the tests and the other diagnostics thresholds (1.05 and 3, record 0039) do not change.

## Consequences
- The open question of record 0059 is closed. With 4 origin periods (tiny) every group shows the warning, as before. The demo example needs at least 8 origin years (HANDOVER, P12).
