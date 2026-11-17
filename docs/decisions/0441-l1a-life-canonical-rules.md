# 0441 — Canonical form of the life feeds, age bands, personal fields and the `life` settings

## Context
CV11 and the three life specs say which rows enter the studies; CV04 types the dates; birth dates and sex are personal (blueprint 4.4, CV11).

## Decision
- **Rows that enter** (`canonical/life.py`, applied as the F1bc feeds are): DV-LIF-01 (BLOCKING, row excluded), -02 (unmapped labels of status, segment, policy_type, channel, premium_frequency and sex become UNMAPPED; a row with an UNMAPPED status is excluded), -03 (age_band invalid: excluded), -04 (entry after valuation: excluded), -05 (identical duplicates once, conflicting: the later source row); DV-LEV-01, -02 (UNMAPPED, kept, enters no rate), -03; DV-FFL-01, -02, -03 (currency UNKNOWN), -04. The other rules compare rows of a contract over time or two feeds: checked by the quality report (0442), applied by the exposure (0445).
- **Age band.** "45" is one age, "45-49" a band (x ≤ y, both 0 to 120), "45+" an open top band: lower age 45, no upper age. Spaces are ignored; anything else ("45.5", "forty", "49-45", "121") fails DV-LIF-03. The canonical frame carries `age_low` and `age_high`; CV11 uses the lower age for the arithmetic. A band wider than `age_band_width` is not split (decision of 0445 for its label). Accepting "x+" widens DV-LIF-03; the spec text changes with it (life_in_force 0.3.0).
- **Amounts** are kept as given: no sign is turned. CV05 asks for positive magnitudes and the specs list a negative amount (DV-LEV-09, DV-FFL-07) as a reversal; a fund switch is negative out of its fund and positive into the other (DV-FFL-06).
- **Currency**: fund_flows by DV-FFL-03; life_in_force and life_events keep what they carry (the exposure uses no currency; the amounts-based view is in the contract's own currency, 0446).
- **Personal fields.** A birth date is personal data in AL01 (`birth_date`): recognition drops the column and the manifest lists it under `personal_data_dropped`. Sex is dropped after mapping unless `life.use_sex` (`life/load.py`), and listed the same way; the life feeds get a mapping record in the manifest only when they are loaded.
- **Settings.** `RunSettings.life` (`life/settings.py`) holds the six defaults of CV11: `age_definition` age_last_birthday, `exposure` central, `study_cells` calendar_year, `age_band_width` 5, `reporting_lag_months` 3, `use_sex` false. Like every setting it enters the manifest and the run id, so every run id moves once.

## Consequences
Tests: `tests/canonical/test_feeds_life.py` (age bands, each excluding rule, the switch sign, birth date and sex, the settings against the CV11 defaults).
