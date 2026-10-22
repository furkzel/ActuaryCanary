# 0030 — Quality checks, their denominators and the score

## Context
DQ01 needs, per rule, the rows checked and the rows that failed. Some rules of spec/data are applied by the canonical step while it builds the feed (empty keys, duplicates, unmapped labels); the rest need the finished frames. Only claim_valuations and claims feed the analyses, yet the owner's test for messy_headers asks for the duplicated premium rows, so the other four concepts must be read and checked too.

## Decision
- A check is a function of the canonical frames that returns rows checked, rows failing and up to five source references (file, sheet, row), or nothing when the fields it needs are not loaded. Rules the canonical step applies are scored from its findings, with the rows read as denominator.
- Rows checked is the number of rows the rule is about: all rows for row rules, consecutive valuation pairs for DV-CLV-07 and DV-CLV-15, claims for DV-CLV-13, claims with a policy id for DV-CLM-09. Several findings of one rule add up, capped at the rows checked.
- Rules for policies, premiums, expenses and market are implemented from generic building blocks (present, unique, ISO shape, classes, order, sign, month end, exists in another concept). Not built: DV-PRM-07, DV-PRM-08, DV-MKT-04, DV-MKT-06 to DV-MKT-08; they are listed under "rules not evaluated" in quality.json and the report.
- The pipeline reads and checks policies, premiums, expenses and market for the quality report only; a concept whose required columns are missing is reported as not loaded, never an error. Their specification IDs join the specs recorded in the manifest, so the run id changes once.
- A cast failure (CV07) is scored as a validity rule of weight 1 per concept, because the canonical step reports it although it has no DV rule.
- The overall score is computed over all rules, not as a mean of concept scores (DQ01); field scores use the rules that name the field in their `fields`.

## Consequences
- Reserve jumps and robust-z outliers (blueprint 6.5) are not built; DV-CLV-15 is the only reasonableness rule on payments.
