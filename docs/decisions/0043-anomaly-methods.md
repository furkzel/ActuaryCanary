# 0043 — Anomaly flags: details left open and the measured ground truth (MT08, MT09)

## Context
MT08 and MT09 leave some details open. Their ground-truth tolerances were measured on baseline medium before the tests were written and both fail as specified; the owner chose on 2026-10-22 to keep both specifications.

## Decision
- **MT08:** flows per CV04 on rows with a paid amount; a reserve change needs a rate on both rows, else it is not scored and is counted; groups come from claims, UNKNOWN when missing. Each flag carries claim, date, source row, value, z, threshold and a reason in words.
- **MT09:** amounts of a row whose currency has no rate count as zero; open means OPEN, REOPENED or LITIGATED (CL04); the reserve-change share is over the rows after the first; an empty feature takes the group median. The flagged claims are the ceil(contamination × claims) highest scores of each group; scikit-learn's own contamination cut is not used. Each flag names its three features furthest from the group median.
- **Ground truth (slow tests, strict expected failures):** MT08 recall of the 8 injected extreme payments is 0 (their z is 1.2 to 2.5; at least 0.75 required; other flags 2.7 per 1000 payments). MT09 AUC is 0.63 on the 18 claims whose amounts the faults changed (owner's choice of positives) and 0.55 on all 60 faulted claims (at least 0.7 required).
- Alternatives measured for MT08 and not adopted: grouping also by payment year, recall 2/8; payment over the previous incurred, 5/8 with 83 other flags per 1000.

## Consequences
- The methods run and flag; their recall on the synthetic faults is reported, not claimed. A specification change is open for the owner.
