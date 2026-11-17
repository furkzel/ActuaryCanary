# 0443 — Reference table format, checks and conversion

## Context
MT20 needs expected decrements from a reference table (CV11). The format must say what a table is (decrement, licence) as well as hold its rates, and a table must enter the run id like any input.

## Decision
- **Where.** `reference_tables/` inside the data folder; every `*.csv` there is a table. (Sheets are read only directly in the data folder, so these files are never taken for a feed.)
- **CSV.** One key column, `age` (whole years, 0 to 120) or `policy_year` (whole, 1 or more); `rate`; optional `rate_kind` (`q`, `mu` or `m`, one value for the whole file), `sex` (FEMALE or MALE), `select_duration`, `product`. Column names are trimmed and lower-cased; nothing else is recognised.
- **Sidecar** `<stem>.yaml` (a separate file, not header lines: it stays readable and a CSV stays a plain CSV): `name`, `decrement` (DEATH, DISABILITY, LAPSE, SURRENDER), `source`, `licence` required; `description` and `rate_kind` (when the CSV has no such column) optional. A table without a sidecar is not used: its decrement and licence cannot be known from the rates.
- **Checks.** Sidecar present and complete; exactly one key, whole numbers in range; one rate kind of the three; every rate present, 0 ≤ q < 1, μ and m ≥ 0; key and group columns unique; no age or policy year missing between the lowest and the highest of each group (sex, select duration, product). A failing table is not used and listed with all its reasons.
- **Conversion** (CV11): μ = −ln(1 − q) with central exposure; q = 1 − e^(−μ) back; **m is taken as μ** (a central rate over a year of constant force equals that force).
- **Hashes.** SHA-256 of the CSV and of the sidecar of every table used enter the run id (one entry `reference_tables` after the mapping entries) and the manifest (`reference_tables.used`: name, file, sha256, sidecar_sha256, rows, decrement, key, rate_kind, source, licence; `reference_tables.not_used`: file and reasons). Without a `reference_tables/` folder holding a CSV the manifest has no such key and the run id is what it was.
- **The generator's tables** (`reference_mortality.csv`: age, rate_kind q, rate; `reference_lapse.csv`: product, policy_year, rate) have no sidecar. Read as they are they are listed "not used: no sidecar". The tests write the sidecars beside copies of them (`tests/life/test_tables.py`); with that, both are valid (the lapse table keyed by policy year with `product` as a group, `rate_kind: q` in the sidecar). The generator does not change in L1a; writing the sidecars there is a small later change.

## Consequences
Documented in `docs/guide.md` ("Reference tables", with a five-age example). Tests: `tests/life/test_tables.py`.
