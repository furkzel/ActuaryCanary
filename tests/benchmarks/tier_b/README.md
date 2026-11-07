# Tier B references

Frozen reference values for the tier B methods (MT11–MT22), decision 0270. One folder per reference:
`manifest.yaml` (source, tool and version, how produced, `checked_by_owner`), the input CSVs and `values.csv`
(quantity, key, value, rel_tol, note). Hand-worked cases are in `tests/fixtures/hand/tier_b/`.

| Reference | Spec | Kind |
| --- | --- | --- |
| `MT11-odp-bootstrap-raa`, `-genins` | MT11 | package + numpy |
| `MT12-munich-chain-ladder-mcl` | MT12 | package |
| `MT13-benktander-raa`, `-genins` | MT13 | package |
| `MT14-tail-curves-raa`, `-genins` | MT14 | package |
| `MT17-severity-fits`, `MT18-gpd-fits` | MT17, MT18 | scipy |
| `MT19-cox-ovarian`, `MT19-cox-lung` | MT19 | R survival |
| hand: `MT13-benktander-4x4`, `MT15-separation-4x4`, `MT16-frequency-severity-4x4`, `MT18-gpd-closed-forms`, `MT19-kaplan-meier-ten-times`, `MT20-credibility-actual-over-expected`, `MT21-reinsurance-twelve-claims`, `MT22-back-test-four-origins` | MT13–MT22 | exact fractions |

Regenerate (by hand; the tests never run these): from the repository root, with `PYTHONPATH=tests/benchmarks/tools`,
`uv run python tests/benchmarks/tools/freeze_chainladder.py [munich|raa|genins]` (about 5 minutes),
`freeze_scipy.py`, `freeze_survival.py` (needs Rscript with survival), `build_hand_fixtures.py`.
`check_km_hand_fixture.R` compares the Kaplan–Meier fixture with R.

The bootstrap references are re-frozen (decision 0282): the package resamples the unscaled residuals (with `hat_adj=False` it applies no degrees-of-freedom adjustment), the freeze script applies the adjustment sqrt(n / (n - p)) of MT11 on top and fits the package's chain ladder on each pseudo-triangle alone, because the package fitted on all simulations as one batch mixes them. The simulation rows are therefore not independent of the spec, and only the mean (within 5 per cent of the chain-ladder reserve) and the scale parameter are pass criteria; percentiles and the standard deviation are information.

The tail references carry the inverse power tail with the infinite product (RAA 1.10534, GenIns 1.32130 against the 100-period 1.10148 and 1.29243) as information (decision 0614). The Cox references freeze coefficients, standard errors, log-likelihoods and the overall tests; the Grambsch–Therneau test, the concordance and the baseline survival have no frozen reference and are information until one is frozen from R (`cox.zph`, `concordance`, decision 0616). `MT13` freezes the Benktander, Bornhuetter–Ferguson and chain-ladder rows only; Mack's credibility weight was removed from the spec (decision 0613).

A manifest may carry an `information` list: values of variants that a decision dropped (the Munich lambda with every link, decision 0607; the tail with the 1e-4 stopping rule, decision 0608). They are not pass criteria and have no row in `values.csv`.
