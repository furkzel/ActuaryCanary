# 0448 — Golden moves of L1a

## Context
`just golden` ran once at the end of L1a (2026-11-17). Rule: no estimate, measure or range value may differ; every changed entry is named with its cause.

## Decision
The renewed copies `tests/report/golden/baseline_tiny.json` and `baseline_tiny_tr.json` differ from the C1 copies only here (compared leaf by leaf, then keyed by concept, setting name, spec id and output name; every other leaf is identical in both languages):
- **M01 coverage** (`pages[0].body.coverage`): three rows added, `fund_flows`, `life_events`, `life_in_force`, not loaded (the life concepts are built, 0440); the rows of the eleven other concepts are unchanged, only their positions in the alphabetical list move.
- **Settings** (`reproducibility.settings`): six rows added, `life.age_band_width` 5, `life.age_definition` age_last_birthday, `life.exposure` central, `life.reporting_lag_months` 3, `life.study_cells` calendar_year, `life.use_sex` False (0441); no other setting changes, the rest move by position.
- **Specs**: AL01 1.2.0 → 1.3.0 and AL02 1.2.0 → 1.3.0 (the life aliases moved, 0440).
- **Outputs**: `quality.json` 37,859 → 40,212 bytes and its SHA-256: the coverage of the three concepts and their 27 rules listed as "life_in_force is not loaded" (and the like) among the rules not evaluated.
- **Run ids** (the settings and the spec versions are inputs of the id): English `779e22b6b4b6e3a3` → `4331801264fb9b36`, Turkish `77baa3bd261c52f9` → `2964813d398af169`.

No figure of any page moved. The baseline has no life feed, so no `life_exposure.csv` and no data-page line.

The guide named the example run ids of 1.3.0; it now names those of the committed example manifests after C1 (demo `c6d0ee3c598ec090`, baseline `779e22b6b4b6e3a3`, messy_headers `4921edeee32f018d`), the three failures C1 left. The committed examples are regenerated at Gate v1.4, not here: their run ids will move then for the reasons above.

## Consequences
`tests/report/test_golden.py` passes on the new copies.
