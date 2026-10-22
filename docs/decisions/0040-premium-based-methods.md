# 0040 — Bornhuetter–Ferguson, Cape Cod and expected loss ratio: inputs and the premium benchmark

## Context
MT03 to MT05 need earned premium per origin and a prior. The benchmark validations of MT03 and MT04 need a published triangle with premium; raa and genins have none.

## Decision
- The methods take the MT02 result of the same triangle (pattern = selected CDF at the latest age) and earned premium per origin as an array the caller matches by origin label (PR02); they run on accident or underwriting origins only.
- An origin with missing, zero or negative premium, or without a prior, is not run and keeps its reason; the others run. MT04 uses every origin with positive premium (origins_used = all).
- Prior per origin: the register's entry for the origin, else its entry for the scope, else the Cape Cod ratio of the same triangle, labelled "data-derived prior" (record 0011).
- New benchmark `tests/benchmarks/clrd_wkcomp`: the CAS Loss Reserving Database workers' compensation triangle (cumulative paid, all companies) with net earned premium, frozen from chainladder 0.10.1 as record 0007 describes: factors, ultimates, Mack standard errors, BF with prior 0.65 and Cape Cod with no trend and no decay. `checked_by_owner: false`.

## Consequences
- BF and Cape Cod match the reference to 1e-9 relative and the hand fixtures exactly.
- The premium array per origin is built when the methods are wired into the reserving module.
