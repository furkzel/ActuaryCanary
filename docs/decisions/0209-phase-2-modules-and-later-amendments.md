# 0209 — Phase 2 module requirements and the amendments left for later

## Context
Blueprint 10 states what M07 to M13 require. Some measures need more, or less, than the blueprint's list (as in record 0014). Several tier B methods belong in version 1.0 modules that this item may not change.

## Decision (proposed, draft)
- **M07** requires recoveries or claim valuations (the to-date fields, record 0203).
- **M08** requires treaties, plus reinsurance transactions or claim valuations.
- **M10** requires the ledger and at least one feed to compare it with.
- **M11** requires life_in_force or fund_flows (blueprint: in-force plus life events). This is because LF04 needs only fund flows; life_events is optional and improves dating.
- **M12** requires claim valuations; interest rates are optional (the discounted view).
- **M13** requires claim valuations and claims.
- Modules list their blocking DV rules, outputs and report page outline.
- **Amendments for the building items** (not made here):
  - M04 gains MT12 to MT16 (tier B methods item).
  - M03 gains MT17 and MT19 (severity and extreme values item).
  - M06 gains MT18 (severity and extreme values item).
  - CV08 changes only after the threshold decision (record 0210).
  - CV03 absorbs CV09 (reinsurance item).
  - CV02 drops its "DISCOUNTED values are not part of version 1.0" rule (uncertainty and discounting item).
  - RS03 points to RS05 for the bootstrap (uncertainty and discounting item).
  - market keeps its kinds (record 0201).

## Consequences
- Until those amendments, the tier B methods appear only in M12 and M13, through their uses.
- The amendments change built specs, and so the run id. Each building item regenerates the goldens.
