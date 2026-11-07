# 0328 — The examples and the demo keep their inputs

## Context
"Done when: M12 and the discounted basis work end to end on `examples/baseline` and the demo". The example folders hold the six workbooks and no interest rates; `canary demo` runs the demo folder with default settings, and the packaged program's manifest comparison (`packaging/compare_manifests.py`) reads the same folder.

## Decision
- No interest-rate workbook is added to `examples/` or the demo. Their reports show M12 as the default run gives it: no curve is named, so nothing is discounted; the Mack and bootstrap ranges appear where the methods ran, and the reason for the rest is in the module's line.
- The end-to-end check with a curve is made on copies of the two folders with the `interest_rates.xlsx` that the generator writes for the same scenario (`phase2/`), named with `--curve TRY_GOV`; its run ids are in the handover. A slow test runs the demonstration folder with a curve written in the test.

## Consequences
- The shipped examples change only by the new outputs and the module entry. Whether the demo should ship a curve is the owner's choice.
