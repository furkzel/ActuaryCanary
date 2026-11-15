# 0813 — Fx0: the last-digit difference of M08 is an order of summation; stated orders

## Context
Row 6 of the criteria table of 1.3.0: two runs on the demo folder gave the same run id and different bytes in `reinsurance_reconciliation.csv` and `measures.csv` (and so in `manifest.json` and the file table of `report.html`). It appeared when the demo got treaties.

## Evidence
- **Reproduced.** Three `canary run` on `examples/demo` with the same settings and the shipped profile (record 0812), in one session on one machine (4 cores): run 1 against runs 2 and 3 differed in exactly those files. The rows: the treaty year QS_PROPERTY 2016 of the reconciliation (`difference` -0.02463144102 against -0.024631441), two rows of RI03 (QS_PROPERTY, claims side: numerator 79500.02 against 79500.02000000002, and the ratio) and four of RI05. No other file and no other measure.
- **Mechanism, shown alone.** A polars `group_by` without `maintain_order` returns its groups in an order that changes from call to call (200 calls on a hand frame of 3,000 rows and 700 groups gave 200 different orders). A float sum over those rows then lands on one of several last digits (300 calls: four values of the same total, apart by one unit in the last place). Sorting the grouped rows, or `maintain_order=True`, gave one value in every call.
- **Where it entered.** `reported_claims` (reported ceded amounts per claim, unordered) summed per treaty year in `reported_by_section`; the latest valuation per claim (`group_by("claim_id").last()`, unordered) summed per origin in `net_share_by_origin` (RI05) and per section and size band in the module; `layer_use` summing the unordered last rows of the units; the allocation weights (unordered groups) whose order decides the split to cents and its sums.
- **Not the hash seed.** After the change, runs with `PYTHONHASHSEED=0` and `=4242` are byte-identical to the others.
- **Also the order of the input rows.** The new test shuffles the treaty and transaction rows of a small programme: before the change the reconciliation moved in the last digits (404.71999999999997 against 404.72), because the sums of a claim's movements ran in file order.

## Decisions
- **An explicit order where the order enters, no rounding.** In `modules/reinsurance.py`, `convert/allocation.py`, `methods/reinsurance/` and the two reinsurance measure files every `group_by` whose result reaches a table or a sum is followed by a sort on its keys (or keeps a defined input order with `maintain_order=True`), every `unique` on a key keeps the first row in order, every `partition_by` keeps its order, and every join with a stated `how` says `maintain_order="left"`.
- **The movements have one order.** `reinsurance_run` sorts the reinsurance transactions by treaty, booking date, type, claim, policy, transaction id and amount before the allocation and the reported sums. The split of each movement does not depend on the other movements, so only the order of summation changes. The treaty rows needed nothing: the sections are already sorted by stage, treaty and inception.
- **One file beyond the item's list.** `measures/reinsurance_programme.py` (RI03 to RI05) is not named in the allowed area; the RI05 part of the defect is there (`net_share_by_origin`), so it received the same ordering changes and nothing else.
- **Tests.** `tests/modules/test_m08_order.py` (fast): seven tables of a programme of 48 claims, two quota shares and a layer with amounts in thirds and sevenths are the same bytes in a second run and after shuffling the treaty and transaction rows (three seeds); it fails on the code before the change. `tests/cli/test_demo.py` compares the manifest and the two files of the demo and of a run byte for byte (slow).

## What moved
Against a run of the code before the change on the same machine: 6 of 29,445 rows of `measures.csv` (RI03 2, RI05 4), largest relative change 2.7e-16; one row of `reinsurance_reconciliation.csv` (the `difference` of QS_PROPERTY 2016, a difference of two sums of 90,459, moved by 4e-10); in `report.html` only the table of file hashes. The run id is unchanged (`713ca5af937d4139`): it does not depend on outputs. No estimate, range or finding text moved. After the change seven runs (three plain, two hash seeds, two more) are byte-identical in all 69 output files.

## Not fixed, observed
With `POLARS_MAX_THREADS=1` the same run differs from the 4-thread runs in the last digit of 172 rows of `measures.csv` (RC04 109, RI01 14, RI03 35, RI04 14): polars sums a group in parts per thread, so the last digit of a grouped float sum depends on the number of threads, on every measure and not only on M08. Two runs on one machine agree; the bytes of outputs on machines with other core counts may differ in last digits (the run id does not). This is older than M08, outside this item, and is left for the owner to weigh (the golden test compares with a tolerance; the examples tests compare run ids).

## Consequences
The committed demo report carries hashes of the three moved files from a run before the change; stage 3 renews the reports of the examples.
