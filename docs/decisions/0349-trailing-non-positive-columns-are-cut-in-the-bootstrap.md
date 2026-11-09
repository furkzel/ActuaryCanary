# 0349 — Trailing non-positive columns are cut in the bootstrap (MT11 1.2.0)

## Context
MT11 stopped when any development column of incremental paid summed to zero or less. Short-tail lines have fully developed late columns whose increments are zero or small recoveries, so on the demo it ran for one line of four (MOTOR_TPL); the other three fell back to the Mack range in M12 and there was no simulated total of all lines (0624, 0323).

## Decision (owner)
- When the last development columns of the paid triangle have a non-positive sum of incremental paid, the model is fitted and simulated on the triangle cut after the last column with a positive sum. The cut columns carry no simulated development (their chain-ladder factors are 1) and the simulated reserve is the chain-ladder reserve of the cut triangle.
- A non-positive column that is not part of that trailing block (a column with a positive sum comes after it) still stops the method; the reason names the column. A triangle with no positive column stops it too (column 0 is named).
- The method fits the volume-weighted chain ladder of the whole triangle as well and reports the difference of the two reserves. It equals the MT02 reserve when the factors beyond the cut are 1; the method warns (`CUT_RESERVE_DIFFERENCE`) when the difference exceeds 1 per cent of the whole-triangle reserve. The comparison is with the method's own whole-triangle fit (volume-weighted, all diagonals, tail 1), not with the selected reserve of MT10, which M12 handles by its own scaling (0325).
- After the cut the usual conditions apply to the cut triangle: at least 5 origins, n minus p above 2, a positive fitted increment in every kept cell. An origin that is observed in the cut columns is treated as observed up to the last kept column (its cumulative paid there is its latest); several origins can share that last column.
- The cut is part of the method's output (`columns_cut`, `cut_columns`, `cut_reserve_difference`) and is reported:
  - `tier_b_parameters.csv`: rows `columns_cut` (count, note names the columns and ages) and `cut_reserve_difference`, written only for a line that was cut, so no file of a line without a cut changes;
  - `bootstrap_summary.csv`: the sentence in the `note` of the Total row; `risk_measures.csv`: the same sentence in the `note` of the bootstrap Total row;
  - the notes of M12 (so under "What did not run and why" is no longer a line for it, and the cut is listed with the other M12 notes) and one sentence in the part "what the totals rest on" of the uncertainty page, in English and Turkish (`language.yaml`). No finding rule is added.
- Tail factor other than 1: it is applied after the last kept column, as before after the last column.

## Consequences
- MT11 1.2.0, M12 1.1.1 (change log only), registry version. Triangles without a trailing non-positive column give identical results (RAA and GenIns benchmarks, the 4x4 fixture and the earlier Monte Carlo calibration are unchanged); a column with no observed cell at the end of a triangle is now cut instead of stopping the method, which changes nothing for a triangle that already ran.
- The all-lines simulated total of M12 exists whenever every line has a bootstrap, with the line correlation of the register (default 0, independence, 0323), added by `add_lines` as before. On the demo it now exists; the page states what it rests on.
- MT22 re-runs MT11 at past cut-offs for the range calibration (`back_test.csv`): lines that now run in MT11 now have MT11 rows there.
- The cut leaves the oldest origins with no simulated unpaid. When their selected unpaid is not zero, M12 notes "no simulated unpaid to scale to the selected one" (0325), and the line's simulated mean is below the selected total by that amount.
- RS05 does not name the condition and is not amended.
