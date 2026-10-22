# 0056 — The port over the methods, the earlier selection and AE01

## Context
P09's port (0050) returns "not available" until methods exist. RT01, RT02 and AE01 read the selection, RS01 to RS03 are method tables. AE01 compares incurred between two valuations with what the selection at the earlier valuation expected; the spec says it is rebuilt "on data known at v0" with the same parameters.

## Decision
- `modules.methods_port.ReservingPort` answers the port from the reserving result. `selection()` and `measure()` gain a `basis` label: the port answers on the basis the run was made on and refuses another with that reason, instead of mixing the run's ultimates with a measure computed on a substituted basis (`request_for`).
- The selection at the cut-off is MT10 on the incurred triangle: ultimates by segment, line and origin, and the cumulative factors by age for paid and incurred.
- The selection at an earlier valuation on the development grid is recomputed: the triangles are cut to the cells valued on or before it (`truncate_triangle`), origins that had not started drop out, and chain ladder, Cape Cod, Bornhuetter–Ferguson and MT10 run again with the same settings and register. Earned premium of an origin whose period was still open at that date is treated as unknown (premium earned to that date is not rebuilt), so those origins fall back to chain ladder with the reason. Ages beyond the earlier triangle carry the tail factor. A date off the grid, or a register entry that does not fit the shorter triangle, gives "not available" with the reason.
- `Selection.expected` holds the ultimate AE01 measures development against: the chain-ladder ultimate where the selection was chain ladder, the prior ultimate (prior loss ratio times premium) where it was Bornhuetter–Ferguson, as the AE01 spec says; it defaults to the selected ultimate.
- AE01 read the cell at the column of v0 and the last column for every origin, which holds for the oldest origin only. It now finds each origin's cell at v0 by its valuation index and its latest cell, and uses the origin's own ages (found by reading the code, tests added with a four-origin hand fixture).
- RS01 to RS03 are tidy tables by segment, line, triangle and development column or origin, with a note column; a method that did not run keeps its reason in the note. RS02 has no IBNER split (not built).

## Consequences
- RT02, the ultimate ratio of RT01, AE01 and RS01 to RS03 appear in `measures.csv` and the report without further changes.
- The earlier selection costs one more run of the premium methods on a shorter triangle.
