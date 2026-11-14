# 0409 — Golden at the end of F2a

## Decision
`just golden` ran once at the end of stage 5 (2026-11-14) and the diff was read entry by entry. The tiny baseline has no treaties (M08 is skipped, record 0407), so only versions and ids move:
- `findings_spec` RP01 v1.4.0 → v1.5.0 (three new rules KF44 to KF46, record 0408; none fires on the baseline).
- Specs used: CV03 1.0.0 → 1.1.0 (CV09 folded in), M08, RI03, RI04, RI05 0.1.0 → 0.2.0; the recoveries footnote names CV03 v1.1.0.
- Run ids: English beaec8582150a2a3 → fc234ffbb1cfe9c5, Turkish f964565e974e5920 → 560026422b0dc901.
- No estimate, measure value, finding text or file hash other than the report moved.

## Consequences
- The run ids of the tiny baseline after F2a are fc234ffbb1cfe9c5 (English) and 560026422b0dc901 (Turkish). The committed examples are not regenerated (planner decision 6).
