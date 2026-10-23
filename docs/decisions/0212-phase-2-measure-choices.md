# 0212 — Choices in the phase 2 measures

## Context
P20 adds measures for the new modules, continues the numbering per family and asks for zero-denominator and missing-period behaviour. Blueprint 8.1 names LF01 to LF04 and FN01; the others are new.

## Decision (proposed, draft)
- **New IDs.** RC03 (recovery delay), RC04 (recovery development), RI03 (ceded share by treaty), RI04 (result ratio), RI05 (loss ratio volatility gross and net), EX04 (administration cost per policy), EX05 (claims-handling cost per claim), FN02 (unmapped ledger share), RS04 (discounted unpaid), RS05 (simulated reserve distribution) and AE02 (back-test error).
- **Missing periods.** A month with no expense rows is "not computed", never zero, because a missing booking is not a zero cost. Fund flows are zero inside the feed's date range. Ledger months follow DV-LDG-10.
- **RS04.** The paid chain-ladder pattern times the selected unpaid, so Bornhuetter–Ferguson and ELR selections have a timing too; this is labelled.
- **RI04.** It is on the ultimate view, using MT10 on the CEDED basis. Without a ceded selection it falls back to ceded incurred, labelled "incurred view".
- **LF03.** It uses the product-limit estimator on contracts, so that young cohorts are censored rather than counted as lapsed.
- **AE02** serves both back-testing (MT22) and challengers (M13).

## Consequences
- Each measure names a test file under `tests/measures/` that does not exist yet. The building item writes it, and the version-1 measure set in `tests/spec/test_specs.py` grows then.
