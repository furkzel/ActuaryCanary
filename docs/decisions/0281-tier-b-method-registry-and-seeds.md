# 0281 — Tier B method registry and seeded streams

## Context
The item asks to expose each method through "the existing method registry". There is none: the pipeline and `modules.reserving` import the tier A functions directly. Tier B adds random draws (MT11, and the optional MT11 rerun of MT22) whose seed must enter the manifest settings and the run id. Runs carry no seed setting today; the seed of MT09 is a module constant (1).

## Decision
- `methods.registry` is new: one `MethodEntry` per tier B spec (MT11–MT16, MT22, AE02) with the function, the spec version it is tested against, the inputs in words, the triangle it runs on by default and what it draws at random. It calls nothing. `settings(seed)` returns the tier B part of the run settings (the seed and every default parameter of `judgement_tier_b.PARAMETERS`); `randomness(seed)` returns the manifest rows of the random draws, like the row of MT09. Once the integration adds both to the settings record, a change of seed or of a default changes the run id (tested with `run_id`).
- `methods.seeding`: the run seed is `RUN_SEED = 1` until runs have a seed setting. A method that runs once per group draws from `generator(seed, *group)`, a numpy `SeedSequence` whose spawn key is the SHA-256 of the group key, so the draws of a group do not depend on which other groups ran or in which order. Without a key the stream is `default_rng(seed)`, as in the benchmarks.
- `methods.judgement_tier_b` holds every judgement parameter of the tier B specs with its default and allowed values; `parameters` returns one register entry in force per parameter (the user entry or the default), as `methods.judgement` does for tier A.

## Consequences
- Tier A is not in the registry; it stays wired as it is. A later item may add it.
