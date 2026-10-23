# 0084 — The five-second basis change moves to version 1.1

## Context
Blueprint 14.3 also says that changing a basis or a segment in the report takes under five seconds. The report of version 1.0 is a static HTML page written by one run for one basis; it has no switch (records 0072 and 0073). A different basis is a new run: 77 s warm on `large` with four feeds (record 0080), 53–63 s with six (record 0082).

## Decision
The five-second criterion does not apply to version 1.0. It moves to version 1.1, together with a report that can show another basis or segment without a new run. Until then a changed basis is a new run. Blueprint 14.3 is edited for this one criterion only; the two-minute criterion is unchanged. The criterion is moved, not dropped: when the report takes a basis or segment from the page, a performance test measures it.

## Consequences
- Gate G2 no longer counts the five-second part as unmet for version 1.0.
- Nothing in the code changes.
