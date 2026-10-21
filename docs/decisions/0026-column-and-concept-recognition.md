# 0026 — Column, concept and personal-data recognition

## Context
Blueprint 6.2–6.4 asks for deterministic, explainable recognition. Thresholds and tie-breaks change which column feeds which field, so they are fixed here.

## Decision
- Layers per column: canonical name (exact, layer `canonical`); normalised token equals an AL01 alias of the concept (`dictionary`, confidence 1); rapidfuzz `ratio` to an alias at least 85, both tokens at least 4 characters (`fuzzy`, confidence = ratio/100); a column of three-letter codes is proposed as `currency` when no header names it (`values`, confidence 0.6).
- Value profile on the first 5,000 non-empty values: a date or number field is confirmed at 90% of values of its type and rejected below 50%; a classified field is confirmed when half of its distinct labels are AL02 labels, and rejected when its cells are numbers or dates; between, confidence × 0.9. Profiles hold shares and counts only, never values.
- Assignment: each field takes one column and each column one field, highest confidence first (then layer, then column order); the loser's evidence names the winner.
- Concept score = 0.9 × field coverage (required fields count twice) + 0.05 when the concept's keys are unique in at least 98% of rows + 0.05 when the file or sheet name normalises to the concept's id or title. Concepts with every required field come first. No concept is proposed below 0.3 with required fields missing. The best three candidates are kept and shown.
- Personal data: an AL01 personal alias (exact, or ratio ≥ 90 for unnamed headers of 5+ characters), or 90% of values being 11-digit identity numbers (first digit not zero), drops a column whatever its header (CV07). Phone, e-mail, IBAN and person-name profiles drop a column only when its header is not a field alias, so a look-alike `policy_id` is kept. Personal columns cannot be mapped by the user and are recognised again when a saved profile is applied.
- Class labels are mapped through AL02 after normalisation; other labels become `UNMAPPED` and are listed with row counts in the terminal and the manifest.

## Consequences
- On the messy tiny files all 64 columns and 6 personal columns match `truth/column_map.csv`, and the canonical frames equal the baseline's.
- AL01 and AL02 are now in the run's specification list.
- The optional suggestion model (blueprint 6.3 layer 5) is not built.
