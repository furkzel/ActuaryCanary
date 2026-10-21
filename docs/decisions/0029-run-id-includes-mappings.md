# 0029 — The run id includes the column mappings applied

Supersedes the run id determinants in 0023; the rest of 0023 stands.

## Context
Since P05 a mapping profile decides which column feeds which field, so an edited profile changes the outputs of the same input files. With the 0023 determinants the run id stayed the same and `out/<run id>/` was overwritten with different results; only the profile fingerprint in the manifest showed the difference. The owner chose to add the mappings to the id (2026-10-21).

## Decision
- The run id is the first 16 hex digits of the SHA-256 of the canonical JSON of: each input's concept, file name and SHA-256; for each sheet used, its file, sheet, concept and the list of (source column, field) pairs applied; each specification ID and version used; all settings (defaults included); the package version.
- Only what changes the outputs enters: the layer, confidence, evidence and confirmation date of a mapping do not. A run that confirms a layout and the next run that reuses the saved profile have the same id.
- The cut-off actually used is not a determinant: it follows from the inputs, mappings and settings already in the id (0023, amended).
- AL01 and AL02 join the specification list, so the baseline run id changed once with P05.

## Consequences
- Editing a profile gives a new run folder; tests check it.
