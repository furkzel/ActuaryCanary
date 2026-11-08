# 0342 — The uncertainty page (M12)

## Context
M12 1.1.0 lists its report page (headline, ranges side by side, histogram with VaR and TVaR, tail effect, cash flows nominal and discounted with the curve, calibration notes), and P26 left four statements for the page: the line correlation, the TVaR estimator, the number of simulations and the tail count, and when an all-lines simulated total exists.

## Decision
- M12 is a module page of its own (anchor `uncertainty`). Each block that depends on the value basis names it, so the page switches between the bases the run computed (0344).
- Headline per line and for all lines: the reserve with its 5th to 95th percentile and coefficient of variation, from the bootstrap where it ran on the line, else from the Mack lognormal. `risk_measures.csv` has no 5th percentile: for the bootstrap it is the quantile of the simulations in `risk_distribution.parquet` (linear interpolation, as RS05), for Mack the lognormal with the mean and standard deviation of the row. On the discounted basis, a line without a bootstrap shows the present value of its expected cash flows (RS04) and the discount effect, without a range.
- Ranges side by side are drawn as ranges: a light bar from the median to the 99.5th percentile, a dark bar from the 75th to the 95th, the mean as a diamond. The reserve-range chart of 0072 uses the 5th–95th and 25th–75th percentiles of the Mack lognormal, which `risk_measures.csv` does not hold; the table keeps every percentile.
- The histogram of each simulated column is binned in the run (40 bars), with the mean, the VaR at 99.5 % and the TVaR at 99 % of the row of `risk_measures.csv` as lines; the simulations themselves are not embedded (size).
- Two colour tokens name the value bases, `--value-nominal` (warm grey) and `--value-discounted` (teal), apart from paid, incurred and the segments.
- Statements on the page: the correlation between lines from the register entry (default 0, independence, the least prudent choice, 0323), the bootstrap estimator text, simulations and tail count of the file, the Mack estimator, and that a simulated total of all lines exists only when every line has a bootstrap, with the lines that have one.
- Calibration notes: the share of later outcomes inside earlier ranges (the AE02 range-calibration rows of `back_test.csv`, summed over lines per method and horizon), with the records that hold the coverage on model data (0075, 0282, 0325) and the known narrowness of Mack on inflation-driven or long-tailed lines (0062).

## Consequences
- The page reads only files of the run; a run without a curve shows the reason of CV10 instead of the discounted blocks.
