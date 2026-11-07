# 0323 — Lines are added with a correlation of zero unless the register says otherwise

## Context
RS03 and RS05 give a range per origin and for a line's total. The goal asks for risk measures "per line and in total". No specification says how lines add, and the choice moves the VaR and TVaR of the total (the standard error, and the simulated total).

## Decision
- The "all lines" total adds the lines with one correlation between every pair of lines, `line_correlation`, an entry of the register (RS05 parameter), default 0 (independence). The value in force is a row of `assumptions.csv` with who and why. A value outside 0 to 1 is refused.
- Simulated reserves: at correlation 0, simulation b of every line is added (the lines are drawn from independent streams, `seeding.generator(seed, *group)`, so this is the sum of independent reserves). Above 0, each line's values are reordered by the ranks of normal scores with a common factor (Gaussian copula, Iman and Conover reordering) and then added; the marginal distribution of every line is kept. At 1 the values are paired by size. The reordering draws from the stream `generator(seed, "line correlation", "all lines", <basis>)`.
- Mack lognormal: the selected reserves add; the standard error is the square root of the sum of squared standard errors plus twice the correlation times the products of every pair; the lognormal is fitted to that mean and standard error and labelled with the correlation.
- A simulated total of all lines exists only when every line with a selected unpaid has a bootstrap, with the same number of simulations. Otherwise there is none and the notes of M12 name the lines without one: adding the simulated lines only would show a total that looks complete and is not. The Mack total needs a Mack result for every line.
- Independence is the default because it is the sum of what was simulated, not because it is prudent: it is the least conservative choice and the register entry is where a more careful one goes. This is the one choice here that moves a headline figure; the owner may set another default.

## Consequences
- RS03 1.1.0 and RS05 1.1.0 say so. The baseline runs of the repository have one simulated line at most (MOTOR_TPL of the demo), so no all-lines simulated total appears in the golden copy or the examples.
