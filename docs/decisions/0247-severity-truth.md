# 0247 — Severity truth: the distribution of a regular claim, per line

## Context
The extreme-value methods (MT17, MT18) must be scored against the true tail of the severity.

## Decision
- `truth/severity_truth.csv` has, per line with a body distribution, the parameters of the simulation (body, tail probability, Pareto threshold and index, litigation probability and multiplier, superimposed inflation), the tail shape `xi = 1/alpha`, the generalised Pareto scale at the threshold `threshold/alpha`, the probability level of the threshold, the mean, and the quantiles at 0.90, 0.95, 0.99, 0.995 and 0.999. All of them are for a regular claim's cost at base-date prices in the reporting currency, computed from the mixture the generator draws from (a body or Pareto draw, times the litigation multiplier). Catastrophe events, large events, the cap at the sum insured and foreign-currency claims are not part of it.
- `truth/severity_tail_truth.csv` has the mean excess over the quantile at 0.90, 0.95, 0.975 and 0.99.
- Tests: the share of a sample below each true quantile equals the level to four binomial errors; the mean excess equals a sample's; the costs of a book ten times the size of tiny follow the distribution function. A sample quantile is not compared: where the distribution function is flat (PROPERTY just below its threshold of one million, which sits at the 0.99 level) it is not determined by the data.

## Consequences
- Sizes are at base-date prices; the claims inflation index (record 0015) turns them into the amounts of a payment date. A method that fits sizes at value-date prices compares the shape (`xi`), which inflation does not change, and scales the quantiles by the index.
- The life line has no severity (a share of the sum insured) and no row.
