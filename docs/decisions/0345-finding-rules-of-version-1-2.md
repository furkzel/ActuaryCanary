# 0345 — Finding rules of report 1.2 (RP01 1.2.0)

## Context
P27 asks for new finding rules in RP01 for the results of version 1.2, in English and Turkish, each with a firing and a non-firing test. KF01 to KF26 of 1.1.0 stay as they are; the owner reviews the new rules at gate G5, so RP01 stays `draft`.

## Decision
- Eight rules, facts computed in `report/phase2_facts.py` from the output tables and M12:
  - KF27 (line): the Munich incurred ultimate at least 10 % away from the selected ultimate;
  - KF28 (line): the selection (MT10) biased by at least 5 % at the first back-test horizon;
  - KF29 (line): the tail of the curve MT14 chose would raise the selected IBNR by at least 10 %;
  - KF30 (line): a tail 0.01 higher (the step of 0343, a fact) would raise the selected IBNR by at least 25 %;
  - KF31 (line): the generalised Pareto shape at or above 0.5, where the fitted tail has no finite variance (the limit is a constant of the large-loss page, a fact);
  - KF32 (segment): the log-rank test across report years below MT19's significance level (a fact read from MT19);
  - KF33 (run): the 95th percentile of all lines at least 25 % above the selected unpaid, from the bootstrap or Mack;
  - KF34 (run): discounting lowers the selected unpaid of all lines by at least 5 %.
- The 10, 5, 10, 25, 25 and 5 per cent levels are this item's choice and sit in the specification, like the levels of 0070.
- The facts test of the tiny baseline skips the new rules (Munich, MT18 and discounting do not run on four origin years); a slow test on the demo with its curve checks that every fact they name is computed.

- A line sentence is placed on the reserving page of its line by its line, not by its evidence section; the evidence section is a link beside it. Before this item a line rule whose evidence was not `line` was put under its section name and shown nowhere: KF26 (anomaly rate of a line, evidence `anomalies`) never appeared on a page. KF26 itself is unchanged; it did not fire on the examples.

## Consequences
- On the tiny baseline KF28 fires on three lines and KF30 on one; on the demo with its curve KF27, KF28, KF29, KF30 (two lines), KF31, KF33 and KF34 fire; KF32 does not (log-rank p-values 0.744 and 0.475).
- The Turkish wording is new and unreviewed.
