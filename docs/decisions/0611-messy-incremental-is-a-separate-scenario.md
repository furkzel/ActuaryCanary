# 0611 — Amounts per period in the messy scenario: a separate scenario

## Context
Record 0223 left open an option of the generator that writes the messy scenario with incremental amounts. P22 did not build it because the option would change the bytes of the first six feeds of `messy_headers`, which are frozen (0241). The detection of cumulative and incremental amounts of P21 is covered by its hand fixtures.

## Decision
Chosen by the owner on 2026-10-24: the detection is covered by the hand fixtures of P21. The generator option is added as a separate scenario, `messy_incremental`, so that the bytes of `messy_headers` never change. It is built by the new-feeds item (P28), not by an item of its own.

## Consequences
- `HANDOVER.md` lists `messy_incremental` under P28.
- The tiny hashes of `messy_headers` in `tests/fixtures/synthetic/tiny_sha256_v1.yaml` stay valid.
