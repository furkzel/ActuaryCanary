# 0615 — Severity fitting: goodness of fit under truncation and on large groups

## Context
MT17 0.1.0 tested D and A^2 against the unconditional distribution function even with a truncation point, and tested every claim of a group. With thousands of claims every family is rejected, so the rule "lowest AIC among the families not rejected" never applies.

## Decision
MT17 0.2.0:
- With `truncation_point` d > 0, D and A^2 use the conditional distribution function (F(x) - F(d)) / (1 - F(d)).
- New parameter `gof_max_claims` (default 2000): in a group with more claims, D, A^2 and their bootstrap p-values are computed on a random subsample of that size (seed from the run seed, recorded), and the output names the number used.
- The ground-truth test fixes and records its parameter sets, with the families at least as well separated as in `tests/benchmarks/tier_b/MT17-severity-fits`. The 80 per cent selection rate is a proposal (UNVERIFIED; nothing was run).

## Consequences
- The selected family can depend on the subsample; the seed is recorded so a run repeats.
- The likelihood, the standard errors and the AIC still use all claims.
