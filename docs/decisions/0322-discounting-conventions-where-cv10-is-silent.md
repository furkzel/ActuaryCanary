# 0322 — Discounting where CV10 is silent

## Context
CV10 fixes the zero rates, the interpolation, the timing and the discount date. Building it raised four points it does not settle.

## Decision
- Missing whole years of a PAR or FORWARD curve between the given tenors are filled by linear interpolation of the rate in the tenor (par: of c, as the spec says; forward: of f), flat before the first given tenor. The bootstrap and the accumulation stop at the last whole-year tenor given; beyond it the last forward rate is held flat. CV10 1.1.0 says so.
- The curve is named by the option `--curve` or by the register entry (CV10, curve_id); the discount date by `--discount-date` or (CV10, discount_date). A register entry of the user wins over the option. The option is recorded as an entry of `assumptions.csv` by "run settings"; the platform default (the cut-off) has `who = default`. The other CV10 defaults (timing, max_curve_age_days, tail_payment_years) are entries too, set from the register or the settings of the run (`RunSettings.discount`), and have no command-line option.
- The value basis DISCOUNTED is a member of `ValueBasis` but is never given to the triangles: the pipeline builds them on NOMINAL (CV10: nothing of the past is discounted) and records DISCOUNTED in the settings (`bases.value`). It is not combined with INFLATION_ADJUSTED because a run has one value basis.
- `--value discounted` needs a usable curve and is refused with the reason otherwise ("the discounted basis needs a curve: ..."). A curve named on the nominal basis gives the same discounted figures; the value basis then only decides which basis a module reports first. The measures of the past are asked on DISCOUNTED and answered nominal with the note "defined on ... NOMINAL only: shown on that basis".

## Consequences
- CV10 1.1.0 and CV02 1.1.0 (the rule "DISCOUNTED values are not part of version 1.0" becomes a reference to CV10).
