# 0367 — Gate G5b: owner statements on the MT13 and MT15 ground truth

## Context
The first run of gate G5 (record 0365) found two ground-truth deviations on `high_inflation/medium` that its statements did not cover: MT13 on PROPERTY reaches 0.922 (baseline gives 0.958), and MT15 on LIFE / GROUP_TERM_LIFE estimates 32.8 per cent calendar inflation a year against a true claims inflation of 0.

## Decision (owner statements)
1. **MT13 on `high_inflation`.** The ground-truth tolerance of the specification applies to the baseline scenario only. On `high_inflation` the chain-ladder family is expected to be biased by the inflation that MT07 exists to handle, so 0.922 is information, not a failure. MT13 1.0.1 says so in one sentence of its ground-truth validation (change log: "not reviewed by the owner yet").
2. **MT15 on GROUP_TERM_LIFE in `high_inflation`.** Not accepted without a diagnosis. A documented limit of the separation method is information plus a limitation note; a defect of the implementation stops the work and goes to the owner. MT15 is not changed in this item. The diagnosis and its result are in record 0368.

## Consequences
- MT13 1.0.1 and MT15 1.0.1 (patch versions, no algorithm, parameter or number changes) move the run ids, because the versions of the specifications used are an input: baseline `fecc00f2e344bce0` to `0f8a1a92415341c1`, messy_headers `68ce22e143a5d0fd` to `5691ac0e060ab62f`, demo `ab54e1cb5917e20e` to `d144d128a8702802`. Golden copies (both languages), examples and the guide moved by the run ids, the two version strings and the report hash only (`just golden`, `just examples`, diffs read).
- Both versions are marked in their change logs as not reviewed by the owner; the list of record 0365 grows by MT13 1.0.1 and MT15 1.0.1.
