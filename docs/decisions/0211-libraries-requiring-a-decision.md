# 0211 — Libraries the phase 2 drafts would need

## Context
The toolchain is fixed by records 0002 and 0090. P20 asks that methods needing a library outside it say "requires decision" in their spec, and that nothing be added.

## Decision (proposed, for the owner)
| Library | Used by | What for | Alternative within the toolchain |
| --- | --- | --- | --- |
| statsmodels | MT19 | Kaplan–Meier (SurvfuncRight), Cox (PHReg), Schoenfeld tests | numpy for Kaplan–Meier and Greenwood; Cox by partial likelihood with scipy.optimize (about 100 lines plus tests) |
| statsmodels | MT23 | GLM standard errors, analysis of deviance | scikit-learn GLM fit plus covariance (X^T W X)^-1 phi with numpy |
| statsmodels | MT27 | ETS state-space models with likelihood and intervals | Holt–Winters with scipy.optimize; prediction intervals by simulation |

Not needed:
- lifelines (MT19 is covered by statsmodels or its own code).
- shap (MT29 uses scikit-learn's permutation importance and partial dependence).
- R or any other runtime (benchmarks against R are frozen numbers, as in record 0007).

chainladder stays test-only: the reference for MT11, MT12, MT13 and MT14.

## Consequences
- With statsmodels, one dependency covers three specs. It is a widely used library, licensed BSD-3. Its size in the PyInstaller bundle was not measured (UNVERIFIED); the P11 size figures would be re-measured.
- Without it, the severity, tier C and challenger items carry more code and more tests, but the toolchain stays as it is.
- The specs name the choice in `requires_decision`; this record is what the owner decides on.
