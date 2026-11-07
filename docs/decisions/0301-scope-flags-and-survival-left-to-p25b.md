# 0301 — Scope of the severity item: `implemented` flags, wiring and MT19 stay out

## Context
Record 0200 says the item that builds a spec sets `implemented: true` in the same change, moves its aliases and extends the version-1 scope test. The work item for the severity and extremes item allows only `src/actuarycanary/methods/severity/`, its tests and `docs/decisions/`, forbids touching `pipeline.py`, the CLI, the report, M06 and the other method modules, and says that the wiring happens in the integration item P25b. A parallel item (P24) builds other methods on another branch. The handover (Next, P25) also names MT19 (survival analysis) and says M03 gains MT17 and MT19; the work item's four work items and its goal name only size-of-loss fitting and extreme-value analysis.

## Decision
- MT17 and MT18 are implemented and tested in `methods/severity/`. Their `implemented` flag stays `false` in this item. A built spec is listed by the report and enters the run id; flipping it here would move the golden copy, the examples and the guide run ids on this branch and on the P24 branch at the same time, and nothing would use the methods yet. P25b flips the flags of both items, moves the aliases, edits `test_phase_2_scope_is_planned` and regenerates the goldens once.
- MT19 is not built here. It is not in the work items or the goal, and it needs its own Kaplan–Meier and Cox code. The handover lists it under P25; the owner decides whether it is a part of P25b or an item of its own.
- The input contract is one frame of claim sizes (`claim_id`, `size`, `status`, optional `segment`, `line`, `event_code`, `origin_year`), with the size as `size_classes` of CV08 gives it. The slow ground-truth tests build it from `size_classes`, `header` and `status_rows` (`tests/methods/severity/medium_sizes.py`); P25b does the same in the pipeline.

## Consequences
- "Every severity and extreme-value spec shows an implementation and passing tests": MT17 and MT18 do, as code and tests that name them; the `implemented` flag follows in P25b. `just spec-index` still lists them as planned.
- No spec file was changed. The points where the specifications are silent and this item chose are in record 0302; the owner may want some of them written into MT17 and MT18 (listed there).
