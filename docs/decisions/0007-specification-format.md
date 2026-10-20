# 0007 — Specification format

## Context
Blueprint principle 2 asks for one specification per rule, readable without code. Later work items implement and test exactly what the specs say, so the specs must be machine-checked.

## Decision
- Each spec is one YAML file in `spec/<kind>/`, validated by pydantic models in `src/actuarycanary/spec/models.py`; unknown keys are errors.
- IDs: data concepts use the concept name (`claim_valuations`); conventions `CV01`…; measures keep the blueprint IDs (`PR01`…); methods `MT01`…; modules `M01`…; alias dictionaries `AL01` (columns) and `AL02` (values). Validation rules inside data concepts have their own IDs (`DV-CLV-01`…). File names start with the spec ID.
- Every spec has `id`, `version`, `title_en`, `title_tr`, `status` (draft or reviewed), `definition`, `notes` and a `change_log`. Specs start at 0.1.0 as drafts; the first reviewed version becomes 1.0.0.
- Fields are referenced as `concept.field`, specs by ID. The loader fails on any invalid file, repeated ID, unknown reference, module that does not list a method or concept its measures need, or alias conflict.
- Label normalisation (blueprint 6.3 layer 1) lives in `spec/labels.py`, because the meaning of the alias dictionary depends on it.
- The index is generated from the files (`just spec-index`); there is no hand-written index.

## Consequences
- Measures, methods and modules can be registered from their files, as blueprint 14.1 asks.
- The spec folder must ship with the application; packaging is later work.
