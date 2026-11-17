# 0444 — No reference table ships; the licence rule; the MT20 default

## Context
CV11 and MT20 left open which open mortality, morbidity and lapse tables ship by default (blueprint 18.2, `requires_decision`). Published national and industry tables carry licences that may forbid redistribution.

## Decision
- The package ships no mortality, morbidity or lapse table. A user's table is read from `reference_tables/` in their data folder (record 0443).
- The generator's synthetic Gompertz–Makeham mortality and lapse tables are the tables of the synthetic scenarios (written into the scenario folder, not into the package).
- A published table would be redistributed only after a licence check written down in a decision record; none is in scope.
- MT20's parameter `reference_table` keeps the default `null` for user data. CV11 0.2.0 and MT20 1.1.0 drop their `requires_decision` entry and name this record and 0443.

## Consequences
- Without a table a life study shows crude rates and their intervals, no A/E (MT20, L1b).
- `tests/life/test_tables.py::test_no_reference_table_ships_with_the_package` fails if a table file appears in the package.
