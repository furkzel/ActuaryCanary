# 0027 — Dates given as text

## Context
A column that mixes real dates and text dates is read as text (record 0017): real dates arrive as `2022-01-31 00:00:00`, others as `31.01.2022`, `31/01/2022` or `2022-01-31`. Slash dates are ambiguous between day-first and month-first; a wrong guess moves amounts between periods. No specification fixes the order.

## Decision
- A text date column is parsed with ISO forms first (with or without time), then the day-first forms `%d.%m.%Y`, `%d/%m/%Y`, `%d-%m-%Y`, each filling only values still empty.
- The order of slash and dash dates is decided per column from its values: a first part above 12 means day first; a second part above 12 means month first (`%m/%d/%Y`).
- When no value decides, day first is used (the Turkish convention) and the column's evidence says "day and month order undecided by the values; day first assumed", in the terminal table and the saved profile.
- Values that parse in no format become empty and are counted as a CV07 finding, as before. Number cells in a date field (spreadsheet serial numbers) are not converted; they become empty with the same finding.
- Whole numbers read into text fields lose their `.0` (`271.0` becomes `271`), so identifiers stored as numbers stay usable.

## Consequences
- Owner check wanted: is day-first the right default for undecided columns?
- A column mixing both orders cannot be read correctly; it would show as a high share of empty dates.
