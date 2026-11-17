# 0447 — Study period and reporting lag

## Context
CV11: whole calendar years before the cut-off; deaths are reported late, so the last `reporting_lag_months` before the cut-off are left out of mortality studies.

## Decision
- **Cut-off of the life study**: the run's cut-off, but not later than the last valuation date of life_in_force (no exposure without data). Events after it are left out.
- **Study period**: from 1 January of the year of the first valuation date to the last 31 December on or before the cut-off (a cut-off of 30 June 2024 ends the study on 31 December 2023).
- **Mortality columns** (`central_exposure_mortality`, `initial_exposure_mortality`, `deaths`, `sum_assured_exposure`, `sum_assured_deaths`) stop `reporting_lag_months` before the day after the cut-off (default 3: a cut-off of 31 December 2025 gives 30 September 2025); a calendar-year cell then holds part of a year. **Lapse, surrender and other exits keep the whole period** (`central_exposure`, `initial_exposure_lapse`, `lapses`, `surrenders`, `other_exits`, `fund_value_*`): a lapse is known when it happens.
- The manifest records `study_start`, `study_end`, `mortality_end` and `cut_off`.

## Consequences
The truth comparison (0446) runs with a lag of 0, since the truth counts every death to the cut-off. Tests: `tests/life/test_exposure.py` (the lag, the last whole calendar year).
