# 0600 — No statsmodels: MT19, MT23 and MT27 on numpy and scipy

## Context
Record 0211 asked whether statsmodels should join the toolchain (0002, 0090) for Kaplan–Meier and Cox (MT19), GLM inference (MT23) and exponential smoothing (MT27). The alternative inside the toolchain was named there for each.

## Decision
Chosen by the owner on 2026-10-24: statsmodels is not added, and no other new dependency comes with these methods.
- MT19: Kaplan–Meier with Greenwood variance on numpy; Cox by partial likelihood with scipy.optimize.
- MT23: standard errors from the covariance (X'WX)^-1 phi on numpy; analysis of deviance from the fitted deviances.
- MT27: exponential smoothing fitted by maximum likelihood with scipy.optimize; prediction intervals by simulation.
- Reference values for the tests may be computed once with an external tool and stored in the fixture file together with the tool name and its version. The tool is not a dependency and is never run by the tests.

## Consequences
- The specs MT19, MT23 and MT27 (0.2.0) drop their `requires_decision` entry and say so in their notes.
- The tier B and tier C items carry more code and more tests than with the library, in exchange for a toolchain and a program size that stay as they are.
- Record 0211 stays as the proposal it was; this record settles it.
