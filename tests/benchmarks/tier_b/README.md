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
