# 0032 — What a BLOCKING finding does to the modules

## Context
Blueprint 6.5: BLOCKING findings stop only the analyses that depend on the affected field. The module specs list required concepts; the measures and methods list the fields they require and may use.

## Decision
- A module is "unable" when a concept in its `required_all` is not loaded, when none of its `required_any` is loaded, or when a BLOCKING finding hits a field that its measures or methods require from a `required_all` concept. The reason is the module's `skip_reason` or the rule, message and counts.
- A BLOCKING finding anywhere else makes the module "limited": the measures and methods that use that field (or, failing that, any field of the concept) are listed as unavailable.
- WARNING and INFO findings never change a status; each finding lists the modules whose measures or methods use its fields.
- M01 (the quality report) is never blocked.
- quality.json and the report mark the status. The run itself still builds triangles and the chain ladder from the rows that remain (the canonical step already leaves out rows without keys, per the data specifications); the pipeline does not yet skip a module marked "unable".

## Consequences
- A report can show chain ladder results next to a module marked unable. Enforcement in the pipeline is left for the owner to decide; it needs the report to handle a missing module.
