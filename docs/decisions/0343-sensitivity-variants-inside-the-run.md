# 0343 — Sensitivity tables: variants rerun inside the run

## Context
P27 asks for sensitivity tables of the selected factors, the tail, the future inflation and a parallel shift of the discount curve, computed by rerunning the methods with assumption variants inside the same run. No specification gives the variants or their sizes.

## Decision
- `report/sensitivity.py` reruns the methods with the run's register changed in one place and writes `sensitivity.csv` (one row per line and variant, with base, value, difference and relative change, or the reason in `note`):
  - development factors: every selected factor f of both triangles moved to 1 + (f − 1)(1 ± 10 %), entered as MT02 `selected_factor` entries; quantity: the selected IBNR (MT10, RS02);
  - tail: the MT02 tail of every triangle raised by 0.01, and the tail of the curve MT14 chose (MT14 `selected_curve`), where MT14 fitted it and no register entry sets the tail; quantity: the selected IBNR;
  - future inflation: the MT07 unpaid at the stated future inflation ± 1 point; with none stated the centre is 0 (value-date prices, which MT07 then reports), so no assumption is invented; MT07 re-inflates the same future payments;
  - discount curve: the present value of the expected cash flows (RS04) with the continuously compounded zero rates moved by ± 100 basis points, D'(t) = D(t) e^(−d t), which equals a curve built with L(t) + d t (tested).
- The base is the run's own result; a rerun with the run's register gives it (tested). The tier B methods are left out of the reruns (none of them feeds MT10 or MT07). The steps are constants in one module and are written to the settings (`report.sensitivity`), so a change of a step changes the run id.
- The tail step was 0.05 in the first demo run and gave +338 % on the short-tailed MOTOR_OD IBNR, which says little; 0.01 is kept.
- Variants of the curve belong to the discounted basis; without a curve their rows give the reason and the page shows it in place of an empty table.

## Consequences
- Four reruns of the tier A methods cost about 3–4 s on the demo on this machine (the demo run went from about 12 s to about 16–20 s, machine not idle); the medium budget test, already over its budget, gets slower too.
- The variants and sizes are the item's choice; the owner can change them in one place.
