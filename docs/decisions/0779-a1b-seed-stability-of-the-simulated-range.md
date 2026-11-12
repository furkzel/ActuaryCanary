# 0779 — A1b: how far VaR 99.5 % and TVaR 99 % move with the seed (R04)

## Context
The second review asked that VaR 99.5 % and TVaR 99 % of the simulated range move by no more than 2 % across 20 seeds. Nothing measured it. Decision of the planner: a documented script, not program output (a user's run must not do twenty bootstraps).

## The script
`docs/tools/seed_stability.py` (`uv run python -m docs.tools.seed_stability <folder outside the repository> [--seeds 1-20] [--simulations N] [--folder F] [--budget-minutes 20]`). The stage cannot be cut out of the pipeline (the bootstrap needs the triangles, the tier B source and the selected reserve of the run to rescale to), so the cheapest correct route is the run itself: for each seed the script calls `pipeline.run` on the demo with its curve, with the seed of `TierBInputs` (one stream per line, `methods.seeding`) and of `run_uncertainty` (M12, the all-lines total) set to that seed, reads the nominal bootstrap totals of every line and of all lines from the run's own `risk` frame, removes the run folder and writes `seed_stability_runs.csv` and `seed_stability_summary.csv`. It checks that the bootstrap recorded the seed it was given, stops with a message before a seed that would not fit in the time budget, writes only into the folder it is given and prints what it did. Spread = (largest − smallest) / mean over the seeds; the table also gives the largest deviation from the mean. The default sizes of the run are untouched; `--simulations` enters as a register entry of MT11 for the study only. The fast test covers the table function on a small frame with a known spread.

## Result (2026-11-12, demo scenario of the repository, seeds 1 to 20, nominal, all lines added at correlation 0)
Time: 20 seeds at 10,000 simulations 3.3 min (9–11 s per seed, a whole run each), at 20,000 3.6 min, at 50,000 4.4 min (about 14 s per seed): the bootstrap itself is a few seconds of a run, so a larger size costs little time here; memory is not a limit. The mean of every line is the same for every seed (the bootstrap is rescaled to the selected unpaid, 0325); 608.5 m for all lines.

| Simulations | Statistic | Mean over 20 seeds (m) | Smallest (m) | Largest (m) | Spread | Largest deviation |
| --- | --- | --- | --- | --- | --- | --- |
| 10,000 | VaR 99.5 % | 1,326.8 | 1,175.2 | 1,382.7 | 15.6% | 11.4% |
| 10,000 | TVaR 99 % | 2,735.8 | 1,408.2 | 7,638.3 | 227.7% | 179.2% |
| 20,000 | VaR 99.5 % | 1,292.5 | 824.4 | 1,380.2 | 43.0% | 36.2% |
| 20,000 | TVaR 99 % | 3,847.7 | 1,516.2 | 22,119.6 | 535.5% | 474.9% |
| 50,000 | VaR 99.5 % | 1,307.6 | 1,077.3 | 1,362.8 | 21.8% | 17.6% |
| 50,000 | TVaR 99 % | 3,123.9 | 1,652.7 | 12,719.2 | 354.3% | 307.2% |
| 10,000, refit with the rule* | VaR 99.5 % | 1,173.3 | 1,141.7 | 1,197.9 | 4.8% | 2.7% |
| 10,000, refit with the rule* | TVaR 99 % | 1,271.8 | 1,213.9 | 1,791.4 | 45.4% | 40.9% |

Spread by line (VaR and TVaR), same seeds:

| Line | Statistic | 10,000 | 20,000 | 50,000 | 10,000 with the rule* |
| --- | --- | --- | --- | --- | --- |
| GROUP_TERM_LIFE | VaR 99.5 % | 3.6% | 2.3% | 1.5% | 3.6% |
| GROUP_TERM_LIFE | TVaR 99 % | 3.6% | 2.5% | 1.6% | 3.6% |
| MOTOR_OD | VaR 99.5 % | 2.6% | 1.7% | 1.2% | 2.6% |
| MOTOR_OD | TVaR 99 % | 3.1% | 1.9% | 1.1% | 3.1% |
| MOTOR_TPL | VaR 99.5 % | 16.0% | 46.4% | 23.7% | 5.5% |
| MOTOR_TPL | TVaR 99 % | 235.2% | 547.8% | 364.4% | 48.6% |
| PROPERTY | VaR 99.5 % | 8.3% | 8.3% | 3.7% | 8.3% |
| PROPERTY | TVaR 99 % | 10.8% | 7.8% | 3.9% | 10.8% |

\* a scratch experiment outside the repository, see below.

## Reading
- **The 2 % target is not met at 10,000 simulations, and no size tried meets it.** All lines: VaR 99.5 % spreads 15.6 % at 10,000, 43.0 % at 20,000 and 21.8 % at 50,000; TVaR 99 % 228 %, 535 % and 354 %. The spread does not shrink with the size on all lines because it comes from a few pseudo-triangles with enormous refitted factors (heavy tail of the simulated total of MOTOR_TPL: with seed 1 the largest of the 10,000 raw simulated totals is 27.0 bn against a median of 303 m): the more simulations, the more such draws. LIFE and MOTOR_OD fall with the size (50,000: 1.5 % and 1.2 % for VaR, 1.6 % and 1.1 % for TVaR, within the target); PROPERTY is at 3.7 % and 3.9 %.
- **Where the instability comes from (R04 diagnostics on the demo, seed 1).** MOTOR_TPL: 63.5 % of the pseudo-triangles have a negative cumulative value, 0.14 % a zero or negative denominator and 0.39 % an extreme factor; PROPERTY: 73.3 %, 0 and 0.07 %. Counted by column on MOTOR_TPL (scratch): every zero or negative denominator (5 and 25 cases in the two columns) and every extreme factor (7 and 43) is in the last two development columns, which rest on two and one link ratio — the same thin factors as R08. The refit of the bootstrap takes the factor of such a column from one or two pseudo-cells, which can be near zero or negative.
- **Scratch experiment, not in the repository, not a change.** The same 20 seeds at 10,000 simulations with the refit setting the factor of a column resting on fewer than two origins to 1.000 (the rule of record 0776 inside `_refit_and_project`): all lines VaR 99.5 % 4.8 % (from 15.6 %), TVaR 99 % 45.4 % (from 227.7 %); MOTOR_TPL VaR 99.5 % 5.5 % and TVaR 48.6 %. One seed still has a large TVaR. The target is still not met, but most of the instability goes with the thin columns. This is information for the owner and the test phase; the refit, the draws, the scale parameter, the residual pool and the rescaling are unchanged here (planner decision).

## Decisions
- The default number of simulations stays 10,000 (the owner decides, as asked). The smallest size that meets the target: none of 10,000, 20,000, 50,000 for all lines; for LIFE and MOTOR_OD 50,000 (LIFE at 20,000: VaR 2.3 %, TVaR 2.5 %, still above).
- The finding goes to the handover: **R04 is diagnosed, not cured**: the pseudo-triangle counts show the cause (thin last columns of MOTOR_TPL and PROPERTY and negative cumulative values) and the 2 % target is out of reach with the present refit. Candidates for the test phase: the rule of 0776 inside the refit, a positive floor of the pseudo-triangle, or a quantile estimator that is less sensitive to single draws; each changes the bootstrap's numbers and needs the owner's decision.
- UNVERIFIED: the study on `baseline medium` and on other scenarios; the experiment with the rule in the refit was run once on the demo with the quick patch of the scratch script, its code is not kept.
