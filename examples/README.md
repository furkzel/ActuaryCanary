# Examples

Three synthetic insurers (no personal data), each with its input spreadsheets and the report of one run (`report/report.html`, `report/manifest.json`). Everything here is written by `just examples` (`docs/tools/refresh_examples.py`); do not edit it by hand.

| Folder | What it is | Feeds |
|---|---|---|
| `demo` | the fixed-seed demo scenario (`synthetic/scenarios/demo.yaml`), ten accident years, a few thousand claims; run as `canary demo` runs it, discounted with the curve TRY_GOV | the six feeds, reinsurance treaties and transactions, recoveries, ledger, interest rates |
| `baseline` | the tiny baseline scenario (the committed tiny fixture) | the six feeds |
| `messy_headers` | the same data with shifted headers, merged cells and mixed formats, to show recognition | the six feeds |

The demo's ledger account-mapping profile is saved confirmed on the generation date (`demo/report/ledger-*.yaml`, the profile the committed run used), so the M10 page reads "confirmed". The other two examples have no ledger; they are the tiny fixtures of version 1.2.0 and are refreshed together with the tests that read them.

## What the demo shows

Beside the reserving pages, the demo has M07 Recoveries (from the 226 recovery transactions), M08 Reinsurance (the treaty programme of the scenario, applied to the gross claims and compared with the booked amounts), M09 Expenses and M10 Ledger reconciliation (65 of 2,400 entity-class-months differ materially from the platform's figure). The report is committed in English; the Turkish page of the demo was run once in a scratch folder at the gate (record 0811) and is not committed.

## Findings that fire on the demo, and why

None of these is a defect of the platform. They are what the generator wrote, read with its known inconsistencies; the generator is not changed before the test phase (record 0811).

| Finding | What it says | Cause |
|---|---|---|
| KF44 (M08) | the programme applied to the gross claims cedes another amount than the data report for XL_TPL in 3 of 13 treaty years | the generator cedes its TPL claims on the occurrence-date index clause while the platform's default is payment by payment, and injected extreme payments (records 0403, 0408) |
| KF47 (M10), data warnings DV-LDG-07 to DV-LDG-09 | 65 material ledger gaps (OUTSTANDING 48, CLAIMS_PAID 9, RI 4, PREMIUM 4) and one unmapped suspense account (297 of ENT_A) | OUTSTANDING and PREMIUM: differences written into the ledger on purpose (IBNR in the outstanding, premium timing); CLAIMS_PAID: injected data faults of the claims feed; RI: the generator converts premium flows at the average rate of the booking month, the platform at the rate of the booking date (record 0423); the suspense account is written on purpose |
| KF35 (M07) | recoveries to date, 7,049,673 TRY, 0.8 % of claims paid | information, not a problem |
| Quota-share premium ceded on gross premium while claims cede after surplus; excess-of-loss premium on written premium, not GNPI; weekend FX rates not published | carried generator inconsistencies of F2a (records 0403, 0405, 0423); they do not fire a finding on the demo | listed for the fix items after the test phase |
