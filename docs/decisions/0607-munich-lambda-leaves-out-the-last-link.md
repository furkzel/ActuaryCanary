# 0607 — Munich chain ladder: the lambda regression leaves out the last link

## Context
Record 0274 found that MT12 as written (a slope through the origin over every cell with both residuals) gives lambda 0.6130 for paid and 0.4208 for incurred on the Quarg–Mack sample triangles, while the chainladder package gives 0.6360 and 0.4362. The package is reproduced to 1e-12 when the last link, which rests on one origin and on an extrapolated variance parameter, is left out. The spec text gave no reason for including that link, and the package is the only independent reference we have.

## Decision
Chosen by the owner on 2026-10-24: the lambda regression follows the reference package and leaves out the last link. MT12 is edited (version 0.2.0, still a draft) to say so, with the reason. The benchmark criterion is the package: lambda 0.6360 (paid) and 0.4362 (incurred) and the ultimates of the package. The variant with every link (paid 0.6130, incurred 0.4208) is kept as information in the manifest of `MT12-munich-chain-ladder-mcl` and is no longer a row of `values.csv`; the test that pinned the difference between the two now checks the information entry.

## Consequences
- P24 can build MT12 and satisfy both text and benchmark. The open point of 0274 is closed.
- The published figures of Quarg and Mack (2004) were not opened (UNVERIFIED); `checked_by_owner` stays false.
