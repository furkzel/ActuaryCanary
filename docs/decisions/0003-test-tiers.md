# 0003 — Test tiers and the 30-second budget

## Context
Fast feedback keeps checks run often; slow checks still need a home.

## Decision
- `just test` runs `pytest -m "not slow" -n auto` and must finish in under 30 seconds. Each fast test stays under 0.5 s.
- Slower tests carry `@pytest.mark.slow`; tests that open real files or cross components may carry `@pytest.mark.integration`. `just test-all` runs everything.
- Fixtures are built in code. Only reader tests open spreadsheets; spreadsheets are read once and cached as parquet keyed by SHA-256 in `.cache/`.
- Hypothesis profile `dev` (25 examples) is the default; CI sets `HYPOTHESIS_PROFILE=ci` (200 examples).

## Consequences
- `just check` (format check, lint, types, fast tests) is the gate on every change.
- A test that grows past 0.5 s must be sped up or marked slow.
