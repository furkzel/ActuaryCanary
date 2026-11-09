# 0365 — Gate G5: owner statements on ground truth, the large run, the basis switch and unreviewed specifications

## Context
The checkpoint for gate G5 (tier B numbers proven, before 1.2.0) was run on 2026-11-09 on `main` at `acf9c1f`. The owner gave four statements for this run.

## Decision
1. **Ground truth on MOTOR_TPL.** The ground-truth comparisons on MOTOR_TPL that fall outside their tolerance are information, not a failure: the synthetic truth files disagree with each other on that line (records 0285 and 0624). The generator is corrected in item P28.
2. **`just bench` on `large`.** It is measured and recorded (time and peak memory). A time above two minutes on the owner's laptop is a finding, not a failure; the reference machine for the budget is the non-blocking `budget` job of the CI (record 0361).
3. **Basis switch.** The five-second criterion is met by a measurement outside the repository: the planner opened the demo report in headless Chromium and measured load 2.35 s and a switch of the value basis of 0.04 to 0.07 s. The owner's machine gave no browser page (the slow test `tests/report/test_demo_report_slow.py` skips there). The measurement is accepted as it stands; it is not reproduced by a test of this repository.
4. **Specification versions not reviewed by the owner.** None of them is marked reviewed by this checkpoint. The list below is from the change logs (version, date of the change, record):

| Specification | Version | Date | Record |
| --- | --- | --- | --- |
| CV02 | 1.1.0 | 2026-11-07 | P26 |
| CV06 | 1.1.1 | 2026-11-08 | 0348 |
| CV10 | 1.1.0 | 2026-11-07 | 0322 |
| interest_rates | 1.1.0 | 2026-11-07 | 0321 |
| RS03 | 1.1.0 | 2026-11-07 | 0323 |
| RS04 | 1.1.0 | 2026-11-07 | 0324 |
| RS05 | 1.1.0 | 2026-11-07 | 0325 |
| M12 | 1.1.0 | 2026-11-07 | 0326 |
| M12 | 1.1.1 | 2026-11-09 | 0349 |
| MT11 | 1.2.0 | 2026-11-09 | 0349 |
| MT17 | 1.1.0 | 2026-11-08 | 0360 |
| MT19 | 1.1.0 | 2026-11-07 | 0341 |
| M03 | 1.1.0 | 2026-11-07 | 0340, 0341 |
| M04 | 1.1.0 | 2026-11-07 | 0340, 0343 |
| M06 | 1.2.0 | 2026-11-07 | 0340 |
| RP01 | 1.2.0 | 2026-11-07 | 0345 |
| RP01 | 1.2.1 | 2026-11-08 | 0347 |
| AL01 | 1.1.0 | 2026-11-07 | 0320 |
| AL02 | 1.1.0 | 2026-11-07 | 0320 |

AL01, AL02, M12 1.1.1 and RP01 1.2.0 are not in the owner's list; their change logs say the same. Every one of these except RP01 (status `draft`) carries `status: reviewed` from its version 1.0.0.

## Consequences
- G5 is measured against these statements; the result, the measured numbers and the deviations that the statements do not cover are in `HANDOVER.md` under State.
- The basis-switch time stays UNVERIFIED inside the repository until the slow test returns a page on some machine.
- The owner's review of the listed versions is still open; P28 carries the MOTOR_TPL generator fix.
