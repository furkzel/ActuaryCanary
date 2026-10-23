# 0074 — Golden test of the report numbers and texts

## Context
P10 asks for a golden test on the tiny baseline that compares a normalised JSON of all numbers and texts behind the report, not the HTML bytes.

## Decision
- The JSON is the report model (0071) of the shared run of the fast suite, with sorted keys and floats rounded to 10 significant digits, so that the last bits of a platform do not count. Figures are included (their numbers are rounded when built), and so are the output fingerprints shown in the reproducibility appendix.
- The copy is `tests/report/golden/baseline_tiny.json`. An intended change is accepted with `just golden`, which sets `ACTUARYCANARY_UPDATE_GOLDEN=1` for that one test, and a review of the diff.

## Consequences
- Any change of a number, a sentence or an output file of the tiny baseline fails the test until the copy is rewritten; this includes method changes from P08b. The fingerprints make the test strict about every output, which is the point of the manifest.
