# 0038 — Selected factors, cell exclusions and the averages shown for comparison (MT02)

## Context
MT02 lets the user override single columns and exclude link ratios, and asks for the volume-weighted, simple and latest-n averages "for comparison". The owner asked that MT02's results do not change and that a zero-denominator cell be handled by exclusion, with the default recorded.

## Decision
- `chain_ladder(..., selected={column: factor})` replaces the average of those columns; the averages stay in the result (`averages`) with a mask of the overridden columns. A selected factor must be finite and positive.
- Cell exclusions are register entries naming the cell (`2024:12-24`). Default: every cell kept, so results equal MT02 1.0.0 when the register is empty. A cell with zero at the earlier age stays in the volume-weighted sums by default, as MT02 says; the diagnostics name it and give the factor without it (record 0039).
- The comparison table shows volume-weighted (all diagonals), simple (all diagonals) and volume-weighted over the latest 3 diagonals; 3 is a display choice, not a setting of the selected factors.

## Consequences
- With an empty register every MT02 number is unchanged; the MT02 tests run unchanged.
- On baseline tiny PROPERTY paid, 12-24 is 4.459 with cell 2024:12-24 and 1.0 without it; the choice is the user's and is recorded.
