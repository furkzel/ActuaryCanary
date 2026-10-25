# 0614 — Tail curves: link number and the remainder of the extension

## Context
MT14 0.2.0 fitted against "age in years" and warned when the last period of the extension added more than 1e-4. Record 0608 removed the stopping rule because it left out the rest of the product. That reason was incomplete: the fixed number of periods leaves out the rest of the product too.

## Decision
MT14 0.3.0:
- The fit variable is the link number x = 1, 2, ... of the fitted links, as in the reference package; for annual columns starting at 12 months it equals the age in years of the start of the link. `fit_from_age` (months) only chooses the first fitted column.
- New output `tail_remainder`: the factor of the periods beyond `extension_periods` relative to tau, computed by running the product to 10^6 periods or until the increment is below 1e-12. New parameter `remainder_warning` (default 0.005): the WARNING "development had not stopped" is given when the remainder exceeds it. This replaces the rule "last period adds more than 1e-4".
- The decision of 0608 (a fixed number of periods, default 100, for parity with the reference and for the cash-flow horizon) stands.
- The manifests of `MT14-tail-curves-raa` and `-genins` carry the inverse power tail with the infinite product under `information` (not a pass criterion): RAA 1.10534 and GenIns 1.32130 against the 100-period 1.10148 and 1.29243. The remainder is 0.35 per cent on RAA and 2.2 per cent on GenIns; a recompute test reproduces both products (the GenIns product reaches the cap of 10^6 periods).

## Consequences
- With the default 0.005 the GenIns inverse power tail gives the WARNING and the RAA one does not.
- An infinite-product tail is not the default; the user may raise `extension_periods`.
