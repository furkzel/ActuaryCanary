# 0014 — Module requirements in version 1.0

## Context
Blueprint section 10 states what each module requires. Version 1.0 reads six concepts only, and some measures need more than the blueprint's required list.

## Decision
- M02 Portfolio and premium requires premiums (blueprint: premium or policy), because every version 1.0 measure of the module needs premium transactions; policies is optional.
- M03 Claims experience requires claim valuations only (blueprint: claim plus snapshots); claims is optional, in line with decision 0004.
- M05 Profitability requires claim valuations, premiums and policies (blueprint: premium plus claims), because earned premium needs policy cover dates.
- Each module lists every concept its measures and methods require and every method they use, directly or through other specs; the loader enforces this.
- Inside a running module, a measure or method whose own fields are missing is skipped with its own reason.

## Consequences
- The skip reasons in the module specs name the exact files to load.
- A policy-only portfolio view needs a policy-count measure, which is not in the version 1.0 subset.
