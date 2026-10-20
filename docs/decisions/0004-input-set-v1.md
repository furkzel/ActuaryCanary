# 0004 — Version 1.0 reads one cumulative spreadsheet per concept

## Context
Insurers hold data in many layouts. Supporting transaction logs, databases and per-period files at once would delay a first useful report.

## Decision
Version 1.0 reads one cumulative spreadsheet per concept, as defined in `spec/data/` (one file per concept; rules for every file in `spec/conventions/CV07-input-files.yaml`). Column names are flexible (alias dictionary); content and grain are fixed. Only `claim_valuations` is required.

## Consequences
- The reader and recogniser stay small and fully testable.
- Other layouts (several files per concept, databases, transactions) are later work and need their own records.
