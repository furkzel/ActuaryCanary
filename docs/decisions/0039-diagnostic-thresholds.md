# 0039 — Thresholds of the method diagnostics

## Context
The owner asked for warnings when the last observed development is still high with tail 1.0, when a factor rests on fewer than three origins or on a zero denominator, when a paid ultimate is below incurred to date, and for thin evidence to be said in every method. The specifications name the diagnostics but not their thresholds.

## Decision
- **Thin evidence:** fewer than 8 origin periods (the demo is to have at least 8, HANDOVER P12). Every triangle method says it; MT08 and MT09 count years of valuations instead.
- **Late development:** the factor of the last column that has a link ratio is above 1.05 while the tail factor is 1.0.
- **Few origins:** a column whose factor rests on 1 or 2 link ratios.
- **Zero denominator:** a usable link ratio with C(i, j) = 0 and C(i, j+1) ≠ 0; the warning gives the factor without that cell and the cell label to exclude.
- **Negative IBNR:** an ultimate below incurred to date, per origin (MT05; the paid chain ladder is checked against the incurred triangle).
- Diagnostics are data (`methods/diagnostics.py`): factor stability (link ratios used, mean, standard deviation, CV, minimum, maximum, average, selected), standardised residuals with means by origin, column and diagonal, the comparison of averages, and warnings with method, code, target and value.

## Consequences
- On baseline tiny: TPL paid 36-48 late development 1.382; PROPERTY paid 12-24 zero denominator; negative IBNR for MOTOR_OD 2025 and MOTOR_TPL 2022 to 2025; thin evidence everywhere (4 origins).
- 1.05, 3 and 8 are named constants in code, not settings.
