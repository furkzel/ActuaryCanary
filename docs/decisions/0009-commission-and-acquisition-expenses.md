# 0009 — Commission is separate from acquisition expenses

## Context
Blueprint 8.1 defines the commission ratio (EX01) as acquisition commission over earned premium, the expense ratio (EX02) as acquisition plus administration, and the combined ratio (RT02) as the sum of the loss, expense and commission ratios. Read literally, commission would be counted twice.

## Decision
- Commission comes only from premium rows of type COMMISSION. ACQUISITION in expenses means acquisition costs other than commission.
- EX01 = earned commission / earned premium; EX02 = (ACQUISITION + ADMINISTRATION) / earned premium; RT02 = ultimate loss ratio + EX02 + EX01.
- Commission, ceded premium and reinsurance commission are earned with the same pro rata pattern as the premium of their policy (PR02), so EX01 and RI02 do not depend on booking timing.

## Consequences
- No double counting in the combined ratio.
- A company whose expense file includes commission under acquisition must map that part to another type or leave COMMISSION rows out of premiums; the user guide must say so.
