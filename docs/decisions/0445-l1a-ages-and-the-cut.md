# 0445 — Ages, policy years and the cut of study time

## Context
CV11: no birth dates; age moves on policy anniversaries; cells by calendar year (or policy year), age and policy year; exits from life_events or, without them, by the half-interval rule.

## Decision
- **Anniversary** (`life/ages.py`): the same day of the month whole years after entry; a missing day (29 February) falls on the month's last day, as the generator puts it. Whole policy years at t: anniversaries on or before t. Policy year = whole years + 1.
- **Entry age** = lower age of the first valuation's age_band − whole years from entry to that valuation (DV-LIF-07's action); attained age = entry age + whole years, so age and policy year move together. Terms of a contract (product, entry date, segment, line, sex) are the latest valuation's (DV-LIF-06); an empty segment is LIFE.
- **age_nearest_birthday** gives the same numbers as age_last_birthday: the setting says what the source's ages mean; the manifest (`life_exposure.age_definition`) and the data-page line name it. No half-year shift is made: without birth dates there is nothing to shift by.
- **Output band**: `age_band_width` years from a multiple of the width; a source band wider than the width keeps its width and moves with the years ("40-49" ten years on is "50-59"); an open band stays open ("85+" → "87+").
- **Spells**: from entry, or from the first REINSTATEMENT after an exit, to the first terminal event (DEATH, SURRENDER, LAPSE, MATURITY, TRANSFER_OUT) of the spell (DV-LEV-06); later terminal events of a spell and a reinstatement without an exit before it change nothing. A contract with no terminal event whose status shows an exit is dated at previous valuation (or entry) + ⌊days to the first exit valuation / 2⌋, the type from the status; rows after an exit without reinstatement are ignored (DV-LIF-08). The manifest counts the exits of each kind.
- **Cut**: each spell is cut at every anniversary and at 1 January (with `study_cells: policy_year` only at anniversaries; the period column is then `anniversary_year`, the year the policy year begins) and at the study bounds (0447). Time is half-open, [start, exit).
- Vectorised over spells with numpy: one pass per policy year (as many passes as the longest duration); no loop over contracts.

## Consequences
Tests: `tests/life/test_ages.py` (an anniversary inside a calendar year, a first valuation 17 years after entry, a band source, 29 February, the output bands), `tests/life/test_exposure.py` (spells, cut, half-interval, policy-year cells).
