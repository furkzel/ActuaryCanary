# 0369 — Gate G5: verdict after the G5b fixes (supersedes the verdict of 0365)

## Context
Record 0365 judged gate G5 NOT PASSED on two criteria: the golden test in both languages, and the ground truth per line. Item G5b (branch `s/G5b-golden-tr`, cut from `s/G5-checkpoint`) removed the two causes with records 0366 to 0368. The code of the product is unchanged: `git diff s/G5-checkpoint --stat -- src` shows only `src/actuarycanary/methods/registry.py` (the two version labels of MT13 and MT15, 1.0.0 to 1.0.1, following their specifications; no algorithm change). The five criteria that this branch does not touch keep the result of 0365.

## Re-evaluation of the two failed criteria
- **Golden test in both languages: PASS.** `tests/report/golden/baseline_tiny.json` (English) and `baseline_tiny_tr.json` (Turkish) are compared by `tests/report/test_golden.py`, parametrised over both languages; the Turkish copy holds the Turkish sentence of every finding rule and the Turkish labels of the reserving, uncertainty, large-loss and survival parts and none of their English labels (record 0366); the language is an input of the run id (0224), so the two copies carry two run ids.
- **Ground truth per line within tolerance, baseline and high_inflation medium: PASS with the owner statements.** The two deviations that were open are covered: MT13 PROPERTY on high_inflation 0.922 is information, since the tolerance applies to baseline only (statement 1, record 0367; baseline gives 0.958, inside 5 per cent); MT15 GROUP_TERM_LIFE 32.8 per cent against a truth of 0 is information plus a limitation note, since the cause is a documented limit of the method, not a defect: the independent recomputation agrees with the module to 1e-16, and removing the origin-level growth of claim size (34.8 per cent a year, from sums insured set at the price level of the policy start) brings the fitted growth to -1.3 per cent (statement 2, record 0368). The MOTOR_TPL deviations stay information by 0365 statement 1. No criterion was re-run beyond this: the numbers of the ground-truth run in `HANDOVER.md` are those of 0365; no product code that enters them changed.

## Verdict
**Gate G5 PASSED**, on the owner statements of 0365 and 0367. All seven criteria PASS (the `large` time over two minutes and the basis-switch measurement outside the repository are the findings and the UNVERIFIED item already recorded). Checks on this branch: `just check` 1751 passed; `just test-all` 1935 passed, 21 skipped, 2 min 15 s, no failure (the budget tests, four, passed on this machine in 43 s when run alone).

## Consequences
- Next is the release item for 1.2.0.
- Run ids moved by the two specification versions (record 0367): baseline `0f8a1a92415341c1`, messy_headers `5691ac0e060ab62f`, demo `d144d128a8702802`; tiny baseline in Turkish `b83b4526a8e04040` (was `0698a73e313af299`; held in its golden copy).
- Open for the owner: review MT13 1.0.1 and MT15 1.0.1; P28 carries the generator notes (MOTOR_TPL truth, origin-level severity index of sum-insured lines).
