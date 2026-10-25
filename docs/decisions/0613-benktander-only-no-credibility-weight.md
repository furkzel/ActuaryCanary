# 0613 — Benktander blends: Mack's credibility weight removed

## Context
MT13 0.1.0 gave Mack's credibility weight as Z = p / (p + sqrt p). Mack (2000) gives the optimal chain-ladder weight as c = p / (p + t) with t = E[sigma^2(U)] / (Var(U0) + Var(U) - E[sigma^2(U)]), a volatility ratio that has to be estimated. The weight p / (p + sqrt p) is not that: for a fully developed origin it gives 0.5.

## Decision
MT13 0.2.0 is Benktander only. The option `mack_credibility`, the Z formula step, its output and its assumption are removed; `blend` allows only `benktander`; the weights output is 1 - q^k. The `notes` say that Mack's credibility weight is deferred until an estimator of t is specified, and cite the paper. The property test uses origins with p above 0.2 for k = 200, because 0.9^200 is 7e-10, too close to the tolerance of 1e-9.

The rows `mack_credibility_weight_Z` and `mack_credibility_ultimate` leave `MT13-benktander-raa`, `-genins` and the 4 x 4 hand fixture (`values.csv`, manifests, the scripts that write them and the tests that read them). Every Benktander, Bornhuetter-Ferguson and chain-ladder row is unchanged; the planner recomputed them independently.

## Consequences
- Twenty rows fewer in each package reference, sixteen fewer in the hand fixture.
- A credibility blend with an estimated t is a later, separate specification.
