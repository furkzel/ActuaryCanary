# 0223 — Cumulative or incremental claim amounts

## Context
`claim_valuations` holds amounts cumulative to the valuation date. A source file may hold what was paid in each period. Read as cumulative, such a file gives wrong triangles without any error: the amounts fall and rise from row to row, which DV-CLV-07 lists but cannot explain.

## Decision
- **Detection (recognition).** On a sample of up to 3 000 claims, with all their rows, the amounts after a positive paid amount are compared with it. Cumulative paid never falls (DV-CLV-07), so a fall in at least 20 % of at least 20 such pairs means per period. Fewer pairs, or fewer falls, read as cumulative. Date and number text are parsed as the canonical step parses them; unreadable values give no evidence.
- **Confirmation.** A claim_valuations sheet shows one line, "Amounts: cumulative to the valuation date" or, in yellow, "per period, not cumulative" with the evidence. `amounts=incremental|to_date` on the edit prompt overrides. A sheet in the canonical layout whose amounts are per period is no longer exempt from confirmation, because the data would otherwise be changed without being asked.
- **Canonical step.** `canonicalise(..., amounts)` adds paid, subrogation, salvage, allocated expense and ceded paid up per claim in date order, after duplicate rows are removed (a repeated row is not added twice). An empty amount stays empty and adds nothing. Reserves are stocks and are untouched. An INFO finding `CV07-INCREMENTAL` says that it was done and on how many rows. Sheets of one concept must agree, otherwise the run stops with a message.
- **Profile.** `amounts` is an optional field of the mapping profile (profile version unchanged). A saved value is used as it is; a profile without it (every profile of version 1.0) lets the values decide on each run. The line is left out of the file when empty.
- **Run id.** Per-period amounts are named in the mapping record that enters the run id; cumulative ones leave it as it was.
- The synthetic generator writes cumulative amounts only. The messy scenario is not extended; a generator option for per-period files is left for P22. The test builds the per-period file from the baseline in code.

## Consequences
- The specifications `claim_valuations` and CV07 still describe the canonical frame (cumulative); the input shape is a reading matter. Their text can mention it when they are next amended.
- A cumulative file whose claims are all paid at once at the last valuation looks like neither and is read as cumulative.
