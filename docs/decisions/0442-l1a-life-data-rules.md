# 0442 — The 27 life data rules: where each is applied, none left unbuilt

## Context
life_in_force (DV-LIF-01 to -10), life_events (DV-LEV-01 to -09) and fund_flows (DV-FFL-01 to -08) state 27 rules. F1bc's pattern (0384): rules that decide which rows enter a feed run in the canonical step, the others list rows in the quality report, rules about two feeds name the other feed in `NEEDS`, rules that cannot run yet go into `NOT_BUILT`.

## Decision
- **Canonical step** (`canonical/life.py`, 12 rules): DV-LIF-01 to -05, DV-LEV-01 to -03, DV-FFL-01 to -04 (record 0441).
- **Quality report** (`quality/checks_life.py`, 15 rules, merged into `FEED_CHECKS`): DV-LIF-06 (entry date, product and sex constant; per contract), -07 (the age interval at a valuation, moved back by the whole years since the previous one, meets the previous interval widened by one year; an open band reaches 120; per contract), -08 (back to IN_FORCE or PAID_UP after an exit status with no REINSTATEMENT dated after the exit valuation and on or before the return; per contract), -09 (amounts and term not negative), -10 (a row at every valuation date of the feed from the first row to the first exit status, else to the last date; per contract); DV-LEV-04, -05 (event before the contract's earliest entry date or after the run's cut-off; contracts not in life_in_force are left to -04), -06 (a second terminal event in one spell between reinstatements), -07, -08, -09; DV-FFL-05, -06 (per contract and date, legs within 0.01 of zero and each with a fund_code), -07 (any type but FUND_SWITCH needs an amount above zero), -08 (a CONTRIBUTION after the last terminal event, strictly earlier than the flow, with no REINSTATEMENT after it).
- **DV-LEV-07** compares the status at the first valuation on or after the day the event is *known*: its report_date when given, else its event_date. A death reported after the next valuation shows IN_FORCE there, which is no error of the data (the generator writes it so); a REINSTATEMENT between the event and that valuation excuses it.
- **NEEDS:** DV-LEV-04, -05, -07 and DV-FFL-05 need life_in_force; DV-FFL-08 needs life_events. DV-LIF-08 runs without life_events (then no reinstatement is known).
- **NOT_BUILT:** none. The actions that change the studies (latest values of a contract, entry age from the first valuation, the exit kept, a valuation carried forward, the earliest terminal event) belong to the exposure (0445).

## Faults the generator injects
None in the life feeds: `synthetic/check_phase2.py` checks the 27 rules, and the scenarios (life_book, messy_headers, messy_incremental) mess only headers, labels, date texts and title rows. Measured at size tiny on life_book and messy_headers: every rule evaluated on rows, no finding. The hand cases of `tests/quality/test_checks_life.py` give each check a failing example.

## Consequences
The life feeds appear in "What was loaded" of the data quality appendix with rows and first and last date (valuation_date, event_date, flow_date).
