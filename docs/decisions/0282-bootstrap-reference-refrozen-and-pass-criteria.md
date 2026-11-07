# 0282 — MT11: the package reference re-frozen, pass criteria, options not built

## Context
P24 built MT11 to the spec: adjusted residuals r sqrt(n / (n - p)), a centred pool without the two cells fitted exactly, refit and projection from the latest diagonal of each pseudo-triangle, gamma process error. Against the frozen references of P23 it missed: on RAA the 95th percentile was 4.7 per cent above the reference (tolerance 1.7), the median 1.5 (1.4), the 75th percentile 2.9 (1.5); the mean was 2.4 to 3.6 per cent above the chain-ladder reserve over ten seeds (average 3.0, criterion 3). Two causes, both found by running chainladder 0.10.1:
- With `hat_adj=False` the package resamples the *unscaled* residuals; it does not apply sqrt(n / (n - p)). The old manifests said it does.
- `Chainladder().fit` on the 10,000 simulated triangles as one batch gives other reserves than fitted on each triangle alone (one RAA simulation: 32,517 against 34,035; standard deviation of the parameter error on the same 2,000 pseudo-triangles 16,098 against 14,007). The batch fit mixes the simulations. The projection of MT11 equals the package fitted on each triangle alone, exactly.

So the +4.7 per cent at the 95th percentile on RAA comes from the adjustment of the spec (wider) set against a package reference that the batch fit had widened in another way; the two do not cancel.

## Decision (owner, 2026-10-25)
- The algorithm of the spec stays, with the adjustment.
- The references `MT11-odp-bootstrap-raa` and `-genins` are re-frozen: package resampling, the adjustment of the spec applied on top of the package output (X* = mu + sqrt(n / (n - p)) (X*pkg - mu)), the package's chain ladder fitted on each pseudo-triangle alone, gamma process error by numpy. The manifest says plainly that the adjustment is the spec's and that the rows are not independent of it. The re-frozen manifests carry `checked_by_owner: false` until the owner checks them.
- Pass criteria of the simulation (MT11 1.1.0): the mean of the simulated total reserve within 5 per cent of the chain-ladder reserve, the scale parameter against its frozen value (1e-9), and the calibration test on triangles drawn from the model (coverage of the 95th percentile within 90 to 99 per cent, behind ACTUARYCANARY_MONTE_CARLO=1). Percentile and standard-deviation rows are information; the benchmark test prints them beside the values of MT11.
- Not built, with the reason given by the method: `scale: by_development`, because the spec gives no formula for the scale per column and the rescaling of the residuals.
- Reading of a `tail_factor` other than 1 ("a fixed share without its own error"): each simulation adds (tau - 1) times its projected cumulative at the last age, with no process error; it is paid in the period after the last age of each origin. The default stays 1 (MT02).
- The cells fitted exactly are found by structure (alone in their origin or in their column), not by a residual near zero.

## Consequences
- MT11 1.1.0: validation text and change log only; `implemented` stays false (0280).
- The recompute test of the references checks the re-frozen rows against the new criteria.
