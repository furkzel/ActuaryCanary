# 0028 — Mapping profiles and terminal confirmation

## Context
Blueprint 6.3: the user confirms a mapping once; it is saved as a small, readable, editable file and reused when the same layout appears. P05 asks for `profiles/<fingerprint-of-header-set>.yaml` and a `--yes` option.

## Decision
- Fingerprint: the first 16 hex digits of SHA-256 over the exact header texts, sorted and joined by line breaks. Column order does not matter; any change of text (including a trailing space) is a new layout.
- A profile holds the concept (empty: such sheets are skipped), the date confirmed, the headers, and per column the field (empty: not used), its first layer, confidence and evidence. It is validated on load: fingerprint equals the headers, every field belongs to the concept, no field is used twice; otherwise the run stops with the reason.
- `canary run` reads every spreadsheet in the folder (file names are hints only) and recognises every sheet. A sheet whose headers are all canonical field names needs no profile and is never asked about. A sheet with a saved profile uses it. All other sheets are shown together in one round, one table per sheet (source column, field, layer, confidence, evidence, candidate concepts with scores); the owner accepts, edits (`n=field`, `n=-`, `concept=name`) or skips each; every answer is saved.
- `--yes` never asks: saved profiles are used and new layouts use the proposal without saving it, so nothing unconfirmed is ever stored. Without `--yes` and without a terminal the run stops and says so.
- Profiles live in `profiles/` in the working folder (option `--profiles`), ignored by git like `out/` and `.cache/`: they describe the owner's files, not the product.
- The manifest lists, per sheet used, file, sheet, concept, header row, rows above it, fingerprint, source (`canonical`, `saved`, `confirmed`, `automatic`), the profile file's SHA-256, columns used with their layers, columns not used, personal-data columns dropped and unmapped labels; sheets of other concepts are listed as not used. Only files of concepts the run uses are inputs.

## Consequences
- The messy example asks once (7 sheets), writes 7 profiles and runs without questions the second time.
- Who confirmed is not recorded (no user identity in phase 1); the assumptions register will add it.
