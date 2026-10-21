# 0023 — Run id and manifest

## Context
Blueprint section 12 asks for a run id derived from fingerprints and for a manifest whose rerun reproduces every output fingerprint. The report cover shows the run id, so the report cannot also be an input to the id.

## Decision
- The run id is the first 16 hex digits of the SHA-256 of the canonical JSON of: each input's concept, file name and SHA-256; each specification ID and version used; all settings (defaults included); the package version. These determine the outputs, so output fingerprints add nothing to the id and would make it circular.
- Outputs go to `out/<run id>/`; the same inputs and settings write the same folder again.
- The manifest holds no clock time. Two runs on the same inputs write byte-identical `manifest.json` and outputs; the tests check this.
- Output fingerprints are computed from the bytes in memory while writing. Reading a freshly written 4.8 MB page back took 1.4 s on Windows (file scanning on open) against 0.01 s for the write.
- Specs recorded: claim_valuations, claims (when loaded), CV01, CV03, CV04, CV06, CV07, MT01, MT02, CL01, CL03, RS01, RS02. Mapping profiles are empty (exact canonical names); randomness is empty (no stochastic step).
- Data findings (rule, count, first source rows) are in the manifest as well as in the report.

## Consequences
- A run time, user name or machine name, when wanted, must live outside `manifest.json` or the reproduction rule breaks.
- Within one package version a code change keeps the run id while the outputs may change; the output fingerprints in the manifest, and golden-report tests later (blueprint 13.2), show it.
- Lineage per cell (blueprint section 12) is not written yet; triangle cells carry claim counts only.
