# 0283 — Details of MT12, MT13 and MT14 that the specs leave open

## Context
Building MT12–MT14 met cases the specs do not settle. None of them moves a benchmark or fixture number: all three methods match their references to about 1e-15 relative.

## Decision
- MT12: Q = P / I is defined where incurred is above zero, Q^-1 where paid is above zero as well; q(j) and rho^I use the cells with Q, rho^P the cells with Q^-1. A cell with incurred zero and paid above zero gives the WARNING of the spec and leaves both regressions. A ratio variance resting on fewer than two cells is extrapolated as MT06 extrapolates sigma; on a full triangle this is never needed, because the projection uses the columns up to the second last, which has two origins. Where a projected paid or incurred is not positive the factor is not corrected. `lambdas` (paid, incurred) may be given, for the property that zero gives the separate chain ladders.
- MT13: the weight is capped at 1 only where the reported share is above 1 and 1 - q^k is above 1; there the ultimate is the chain ladder, the closed form with weight 1. The WARNING is given for every origin whose reported share is above 1.
- MT14: a column is fitted when its factor is above 1, as the spec says; the package's threshold is 1.00001, and no reference factor lies in between. The remainder rho is computed as the product over the periods after the extension, so rounding never makes it negative. The fitted tail replaces the MT02 tail only through the register entry `MT14 selected_curve` (value: the curve), which needs the user's reason; `MT02 tail_factor` and `MT14 selected_curve` together are an error. The entries in force then name the curve, the first fitted age and the tail used.

## Consequences
- None for tier A; the default tail of MT02 stays 1.0.
