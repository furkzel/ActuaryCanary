# 0082 — The two-minute budget measured on all six feeds of `large`

## Context
Blueprint 14.3: the largest scenario loads, maps and reports in under two minutes. Record 0080 measured four feeds only. With `policies` and `premiums` as workbooks (record 0081) the budget can be measured as worded. `just bench <folder>` (new) times `pipeline.run` twice in one process: cold (empty reader cache, every spreadsheet read) and warm (parquet cache hit), and prints the time of each step the run announces. The performance test uses the same code.

## Measurement
`just bench data/synthetic/baseline/large`, 2026-10-23, 16-core Windows 11 desktop, not checked to be idle. 994,821 valuation rows, 4,305,801 premium rows, 1,354,169 policy rows, eleven workbooks, run id `480b93713e92884b`. Seconds, cold / warm:

| Step | Before the changes | After the changes |
| --- | --- | --- |
| Import | 2.7 / 0.0 | 2.4 / 0.0 |
| Read and recognise | 53.9 / 1.5 | 15.5 / 1.1 |
| Check against the specifications | 3.9 / 3.5 | 3.4 / 3.4 |
| Triangles, reserving methods | 4.6 / 4.1 | 4.0 / 4.2 |
| Anomalies (MT08, MT09) | 7.1 / 6.8 | 6.8 / 6.8 |
| Measures and modules | 24.8 / 21.5 | 21.2 / 21.5 |
| Writing the tables | 34.6 / 26.0 | 14.9 / 15.0 |
| Report and manifest | 0.7 / 0.7 | 0.7 / 0.7 |
| **Total** | **132.3 / 64.1** | **69.0 / 52.6** |

The budget was missed cold (132 s) and is met after the changes. Two further cold runs of the same code: 77.4 and 83.8 s (warm 63.4 and 54.2 s); the spread comes from the machine, mostly from writing the tables. Peak working set of the process, both runs together: 7.4 GiB (7.2 GiB after the cold run). The anomaly step took 20 s in record 0080 and 7 s here with unchanged code; the earlier figure was not repeated.

## Decision
Two changes. Neither touches a result: on `large` all fourteen output files of the run, `lineage.csv` (352 MB with six feeds) included, have the SHA-256 they had before the changes (run id `480b93713e92884b` both times); the golden test and the messy comparison are the existing tests.
- **Reading.** `read_workbooks` reads the workbooks of a folder several at a time (six at most, or the number of cores) in a thread pool; the parser releases the interpreter lock. Order and errors are those of the sequential loop. Cold reading falls from 54 s to 15.5 s. The cache and its key are unchanged.
- **Lineage.** `lineage.csv` turns sorted source rows into runs. The runs were found with window expressions per key, 24 s on `large`. They are now found over the whole sorted frame by comparing neighbours, 14 s, and the file is the same byte for byte. The file contract (columns, `2-40;45` ranges) is not changed. Not done: a stepped notation for rows that alternate (`240;242;244`), which would shorten the file but change the contract.
- Not touched, because the budget is met: the anomaly flags (7 s), the measures (21 s, of which earned premium 11 s), the specification checks.

## Consequences
- The budget is met with a margin of 35–50 s on this machine and UNVERIFIED on an ordinary laptop: with 7.4 GiB peak, a machine with 8 GB of memory may swap. The owner decides whether the peak needs lowering.
- A slow performance test on `medium` keeps watch: cold under 45 s and warm under 30 s without the import (measured 15.3 s and 10.3 s), and the second run must read less than half as long as the first. `large` itself is measured by hand at each checkpoint with `just bench data/synthetic/baseline/large`.
- Writing the tables remains the second largest cost (15–29 s; 352 MB of `lineage.csv`, 29 MB of `anomalies.csv`) and varies most between runs.
