# 0446 — Exposure and decrements against the generator's truth; `life_exposure.csv`

## Context
The generator's life book moves age on anniversaries and writes, in `truth/life_expected_decrements.csv`, the central exposure (days / 365.25) and the actual decrements by calendar year, product, age and policy year over [1 January of its first year, cut-off]. A study that follows CV11 should recover it.

## Decision
- **Exposure** (`life/exposure.py`): central exposure = days / 365.25 in the cell; initial exposure = central + time from each decrement of the studied kind to the next anniversary (`initial_exposure_mortality` for deaths, `initial_exposure_lapse` for lapses and surrenders); counts `deaths`, `lapses`, `surrenders`, `other_exits` (MATURITY, TRANSFER_OUT); amounts view `sum_assured_exposure` (mortality window) and `fund_value_exposure`, `sum_assured_deaths`, `fund_value_surrenders`, valued at the latest valuation on or before the start of the cell (else the first). DISABILITY is not an exit and is not counted (no morbidity study yet). Events of contracts not in life_in_force enter no cell; their number is in the manifest.
- **Output** `life_exposure.csv` (through `write_table`), keys segment, line, product, (sex when `use_sex`), calendar_year or anniversary_year, age, age_band, policy_year; written and listed in the manifest only when life_in_force has rows, with the conventions under the manifest key `life_exposure`. The M01 data page has one line per segment naming the life feeds and the years of exposure (scope `segment`). A run without life feeds writes exactly the files it wrote before.
- **Tolerance**: 1e-6 per cell, the rounding of the truth file (6 decimals). Both sides use 365.25 days; no other difference is allowed.

## Measured (2026-11-17)
- life_book tiny (325 contracts, 963 cells; lag 0, band width 1): TERM_LIFE, ENDOWMENT_SAVINGS and PERSONAL_PENSION, every cell of the truth within 4.98e-7; deaths equal deaths_reported, lapses and surrenders equal the truth's lapses, in every cell. GROUP_TERM (ages in bands of five) differs by age, because the entry age is the band's lower age (CV11); summed over age, by calendar year, product and policy year, within 2.6e-6 and its decrements equal.
- life_book medium (51,826 contracts, 211,320 in-force rows, 24,902 events; 13,726 cells): PERSONAL_PENSION every cell within 5e-7; TERM_LIFE and ENDOWMENT_SAVINGS one cell each off (0.044 and 0.025 years); the total difference, 0.4189 years, equals exactly the exposure after death of the 6 deaths reported after the cut-off (the platform cannot know them, so it keeps them in force to the cut-off). Deaths equal deaths_reported (631), lapses equal (20,817). Expected decrements with the synthetic table are information only (A/E is L1b).
- **Time**: exposure 0.68 s on life_book medium (reading and canonical form of the three feeds 6.0 s); a run of tiny life_book with its feeds and a table, 5.1 s in all. The demo scenario has no life book (it extends baseline), so medium life_book stood in for it; generated outside the repository in 122 s.

## Consequences
Tests: `tests/life/test_exposure.py` (truth cell by cell on tiny life_book, the banded product by policy year, the helper of the pipeline, the M01 line and its scope, a run without life feeds); `test_the_life_book_end_to_end` is marked slow (written, not run).
